import asyncio
import base64
import json
import re
from collections.abc import Callable
from typing import Annotated

import httpx
from fastapi import Depends, Request, UploadFile
from redis.asyncio import Redis

from saltbox_gateway.config import SETTINGS, logger
from saltbox_gateway.dao.service_dao import ServiceDAO, get_service_dao
from saltbox_gateway.exceptions import (
    ApiProxyRequestException,
    NotEnoughPermissionsException,
    # ProxyOpaClientInitializationError,
    ProxyStaticFileException,
    ServiceDisabledException,
    ServiceEndpointNotFoundException,
    ServiceHasNoEndpointsException,
    ServiceHasNoHealthyInstancesException,
    ServiceHasNoInstancesException,
)
from saltbox_gateway.schemas import ProxyRequestData
from saltbox_gateway.utils.balancing_strategies import BalancingStrategy, balancing_strategy_factory
from saltbox_gateway.utils.httpx_client import HttpxClientSingletoneFactory
from saltbox_gateway.utils.opa_client import AsyncOpaClient
from saltbox_gateway.utils.redis_cache import BaseCache, CustomRedisCache
from saltbox_gateway.utils.redis_config import get_redis
from saltbox_sdk.discovery_client.schemas import OPAConfig, ServiceEndpoint, ServiceInstance, ServiceSchema


class ProxyService:
    def __init__(
        self,
        request_data: ProxyRequestData,
        dao: ServiceDAO,
        balancing_factory: Callable[[str], BalancingStrategy],
        opa_client: AsyncOpaClient,
        httpx_client: httpx.AsyncClient | None = None,
        cache: BaseCache | None = None,
    ):
        self._request_data = request_data
        self._dao = dao
        self._balancing_factory = balancing_factory
        self._httpx_client = httpx_client or httpx.AsyncClient(timeout=SETTINGS.proxy_request_timeout)
        self._opa_client = opa_client
        self._cache = cache

    @classmethod
    async def create(
        cls,
        request: Request,
        dao: ServiceDAO,
        balancing_factory: Callable[[str], BalancingStrategy],
        opa_client: AsyncOpaClient,
        httpx_client: httpx.AsyncClient | None = None,
        cache: BaseCache | None = None,
    ) -> 'ProxyService':
        """Asynchronous factory method to create a ProxyService instance."""
        raw_body = None
        body = None
        headers = dict(request.headers)

        # Body is only sent for methods that typically include a body
        if request.method in ['POST', 'PUT', 'PATCH', 'DELETE']:
            raw_body = await request.body()
            body = None
            content_type = headers.get('content-type', '')
            if content_type.startswith('application/json'):
                try:
                    body = json.loads(raw_body)
                except Exception:
                    body = None

            elif content_type.startswith('multipart/form-data'):
                # Handle multipart form data
                try:
                    form_data = await request.form()
                    body = {
                        'fields': {k: v for k, v in form_data.items() if not isinstance(v, UploadFile)},
                        'files': [
                            {'filename': file.filename, 'content_type': file.content_type, 'size': file.size}
                            for file in form_data.values()
                            if isinstance(file, UploadFile)
                        ],
                    }
                except Exception as e:
                    logger.error(f'Error parsing multipart form data: {e}')
                    body = None
            elif content_type.startswith('application/x-www-form-urlencoded'):
                # Handle URL-encoded form data
                try:
                    form_data = await request.form()
                    body = dict(form_data.items())
                except Exception as e:
                    logger.error(f'Error parsing URL-encoded form data: {e}')
                    body = None
        else:
            raw_body = None
            body = None
            headers.pop('content-type', None)
            headers.pop('content-length', None)

        request_data = ProxyRequestData(
            method=request.method.upper(),
            path=request.url.path.strip('/'),
            query_params=dict(request.query_params),
            headers=headers,
            body=body,
            raw_body=raw_body,
            user=request.state.user,
        )
        return cls(
            request_data=request_data,
            dao=dao,
            balancing_factory=balancing_factory,
            opa_client=opa_client,
            httpx_client=httpx_client,
            cache=cache,
        )

    async def api_proxy(self, service_name: str, path: str) -> httpx.Response:
        endpoint = None
        service = await self._get_service(service_name)
        service_instance = await self._choose_healthy_instance(service)
        if not service_instance.endpoints:
            raise ServiceHasNoEndpointsException(service.name)

        if self._is_swagger_path(path, service_instance):
            endpoint = ServiceEndpoint(
                path=path,
                method=self._request_data.method,
                opa_config=OPAConfig(
                    action='swagger',
                    policy='public',
                    is_partial=False,
                    query_filter_format=None,
                ),
                cache_ttl=0,  # Disable caching for docs
            )
        else:
            endpoint = await self._get_endpoint(service_instance.endpoints, path)

        if not endpoint:
            raise ServiceEndpointNotFoundException(service.name, path)

        url = f'http://{service_instance.host}:{service_instance.port}/{path.strip("/")}'

        # TODO: refactor cache conditions
        if endpoint.cache_ttl > 0:
            cached_response = await self._get_response_from_cache()
            if cached_response:
                return cached_response

        # Partial OPA check:
        # 1) If the endpoint has a policy and is partial, check access
        # 2) If OPA response allows, proceed with the proxy request

        # Full OPA check:
        # 1) If the endpoint has a policy and is not partial check method:
        #     - If method is GET, proxy request and get response. Add response to OPA input and check access
        #     - If method is not GET, add body to OPA input and check access
        # 2) If OPA response allows, proceed with the proxy request

        # service_response = await self._get_response_from_service(url)
        service_response = await self._get_response_or_raise(
            url=url,
            path=path,
            service_name=service_name,
            opa_config=endpoint.opa_config,
        )

        if endpoint.cache_ttl > 0 and self._is_response_cachable(service_response):
            await self._add_response_to_cache(service_response, endpoint.cache_ttl)

        return service_response

    async def _get_response_or_raise(
        self, url: str, path: str, service_name: str, opa_config: OPAConfig
    ) -> httpx.Response:
        service_response = None
        if not opa_config.policy or opa_config.policy == 'public':
            return await self._get_response_from_service(url)

        # TODO: add check for method? (Only GET can be partial?)
        if opa_config.is_partial:
            input_data = await self._prepare_input_for_opa(service_name, path, action_name=opa_config.action)

            opa_response = await self._opa_client.check_access(
                package=opa_config.policy,
                input=input_data,
                is_partial=True,
                unknowns=opa_config.unknowns or [],
                partial_query=opa_config.partial_query or 'allow == true',
                query_filter_format=opa_config.query_filter_format,
            )
            if not opa_response.get('allow', False):
                raise NotEnoughPermissionsException(service_name=service_name, path=path)

            # Add query to request data if provided by OPA
            if opa_response.get('query') is not None:
                self._request_data.query_params.update({'opa_query': json.dumps(opa_response['query'])})
                logger.debug(f'Added OPA query to request: {opa_response["query"]}')

        if not opa_config.is_partial:
            if self._request_data.method == 'GET':
                service_response = await self._get_response_from_service(url)
                logger.debug(f'Service response: {service_response.status_code} {service_response.text}')
                try:
                    json_data = service_response.json()
                    logger.debug(f'Parsed JSON data from service response: {json_data}')
                except json.JSONDecodeError:
                    json_data = {}
                input_data = await self._prepare_input_for_opa(
                    service_name, path, action_name=opa_config.action, object=json_data
                )
            else:
                input_data = await self._prepare_input_for_opa(service_name, path, action_name=opa_config.action)

            opa_response = await self._opa_client.check_access(
                package=opa_config.policy,
                input=input_data,
                is_partial=False,
            )

            if not opa_response.get('allow', False):
                raise NotEnoughPermissionsException(service_name=service_name, path=path, action=opa_config.action)
        return service_response or await self._get_response_from_service(url)

    def _is_swagger_path(self, path: str, instance: ServiceInstance) -> bool:
        """Check if the path is a Swagger or OpenAPI documentation path."""
        current_path = path.strip('/')
        if instance.docs_path and current_path.startswith(instance.docs_path.strip('/')):
            return True
        if instance.openapi_path and current_path.startswith(instance.openapi_path.strip('/')):
            return True
        return False

    async def _prepare_input_for_opa(
        self, service_name: str, path: str, action_name: str, object: dict | None = None
    ) -> dict:
        data = {
            'subject': self._request_data.user.model_dump(),
            'action': {
                'method': self._request_data.method,
                'name': action_name,
            },
            'resource': {
                'service_name': service_name,
                'path': path.strip('/').split('/'),
                'query_params': self._request_data.query_params,
                'object': object,
                'body': self._request_data.body,
            },
        }
        logger.debug(f'Preparing OPA input: {data}')
        return data

    def _is_response_cachable(self, response: httpx.Response) -> bool:
        if not self._request_data.is_cachable:
            return False
        if not response or not response.content:
            return False
        if response.status_code != 200:
            return False
        if 'Cache-Control' in response.headers and 'no-store' in response.headers['Cache-Control']:
            return False
        return True

    async def _add_response_to_cache(self, response: httpx.Response, ttl: int) -> None:
        if not self._cache:
            logger.warning('Cache is not configured, skipping caching response')
            return
        cache_data = {
            'status_code': response.status_code,
            'headers': dict(response.headers),
            'content': base64.b64encode(response.content).decode('ascii'),
        }
        await self._cache.set(self._request_data.cache_key, cache_data, ttl=ttl)

    async def _get_response_from_cache(self) -> httpx.Response | None:
        if not self._cache:
            logger.warning('Cache is not configured, skipping cache lookup')
            return None
        if not self._request_data.is_cachable:
            return None
        cached_response = await self._cache.get(self._request_data.cache_key)
        if cached_response:
            if isinstance(cached_response, (bytes, str)):
                if isinstance(cached_response, bytes):
                    cached_response = cached_response.decode('utf-8')
                try:
                    cached_response = json.loads(cached_response)
                except Exception as e:
                    logger.warning(f'Error parsing cached response: {e}')
                    return None
            logger.debug(f'Cache hit for key: {self._request_data.cache_key}')
            # Фильтруем hop-by-hop заголовки и сбрасываем content-length
            hop_by_hop = {
                'connection',
                'keep-alive',
                'proxy-authenticate',
                'proxy-authorization',
                'te',
                'trailers',
                'transfer-encoding',
                'upgrade',
                'content-length',
            }
            raw_headers = (cached_response.get('headers') or {}) if isinstance(cached_response, dict) else {}
            headers = {k: v for k, v in raw_headers.items() if k.lower() not in hop_by_hop}

            content_b64 = (cached_response or {}).get('content')
            try:
                content = base64.b64decode(content_b64) if content_b64 is not None else b''
            except Exception as e:
                logger.warning(f'Error decoding cached content: {e}')
                return None

            status_code = int((cached_response or {}).get('status_code', 200))
            logger.debug(f'Returning cached response with status code: {status_code}')
            return httpx.Response(
                status_code=status_code,
                headers=headers,
                content=content,
            )
        logger.debug(f'Cache miss for key: {self._request_data.cache_key}')
        return None

    def _build_proxy_headers(self) -> dict:
        headers = self._request_data.headers.copy()
        user = self._request_data.user
        headers['X-User-Id'] = str(user.sub)
        headers['X-User-Email'] = user.email
        headers['X-User-Email-Verified'] = str(user.email_verified)
        headers['X-User-Name'] = user.name

        return headers

    async def _get_response_from_service(self, url: str) -> httpx.Response:
        headers = self._build_proxy_headers()
        retries = SETTINGS.proxy_retries if self._request_data.method in SETTINGS.proxy_retry_idempotent_methods else 0
        backoff = SETTINGS.proxy_retry_backoff_base
        for attempt in range(retries + 1):
            try:
                response = await self._httpx_client.request(
                    self._request_data.method,
                    url,
                    headers=headers,
                    params=self._request_data.query_params,
                    content=self._request_data.raw_body,
                    follow_redirects=True,
                )
            except Exception as e:
                if attempt < retries:
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                raise ApiProxyRequestException(detail=str(e)) from e

            if response.status_code in SETTINGS.proxy_retry_on_status and attempt < retries:
                await asyncio.sleep(backoff)
                backoff *= 2
                continue
            break

        if not response.is_success:
            detail = 'Unknown error occurred while processing the request.'
            if response.content and response.headers.get('content-type', '').startswith('application/json'):
                try:
                    detail = response.json().get('detail', detail)
                except Exception as e:
                    logger.warning(f'Ошибка парсинга JSON из ответа сервиса: {e}')
            raise ApiProxyRequestException(
                detail=detail,
                status_code=response.status_code,
            )

        return response

    async def proxy_static_file(self, service_name: str, path: str) -> httpx.Response:
        service = await self._get_service(service_name)
        if not service.front_config.static_host:
            msg = f'Static host is not configured for service `{service.name}`.'
            raise ProxyStaticFileException(msg)
        url = f'{service.front_config.static_host}/{path.lstrip("/")}'

        logger.debug(f'Fetching static file from {url}')

        static_response = await self._httpx_client.get(
            url,
            headers=self._request_data.headers,
            params=self._request_data.query_params,
        )

        if static_response.status_code != 200:
            raise ProxyStaticFileException(
                detail=f'Failed to fetch static file from `{url}`. Status code: {static_response.status_code}'
            )

        return static_response

    async def _get_service(self, service_name: str) -> ServiceSchema:
        service_data = await self._dao.get(service_name)

        service = ServiceSchema(**service_data.get('data', {}))

        if not service.enabled:
            raise ServiceDisabledException(service.name)

        if not service.instances:
            raise ServiceHasNoInstancesException(service.name)

        return service

    async def _choose_healthy_instance(self, service: ServiceSchema) -> ServiceInstance:
        healthy_instances = [inst for inst in service.instances if inst.healthy]

        if not healthy_instances:
            raise ServiceHasNoHealthyInstancesException(service.name)

        strategy = self._balancing_factory(service.load_balancing_strategy)

        return await strategy.choose(service.name, healthy_instances)

    @staticmethod
    def _path_to_regex(endpoint_path: str) -> re.Pattern:
        regex = re.sub(r'{[^/]+}', r'[^/]+', endpoint_path.strip('/'))
        return re.compile(f'^{regex}/?$')

    async def _get_endpoint(self, endpoints: list[ServiceEndpoint], path: str) -> ServiceEndpoint | None:
        request_path = path.strip('/')
        for endpoint in endpoints:
            if endpoint.method.lower() == self._request_data.method.lower():
                pattern = self._path_to_regex(endpoint.path)
                if pattern.match(request_path):
                    return endpoint

        return None


async def get_proxy_service(
    request: Request,
    dao: Annotated[ServiceDAO, Depends(get_service_dao)],
    redis_client: Annotated[Redis, Depends(get_redis)],
) -> ProxyService:
    httpx_client = HttpxClientSingletoneFactory.get_instance()
    balancing_factory = balancing_strategy_factory(redis_client)
    cache = CustomRedisCache(redis_client=redis_client, namespace='gate_cache')
    opa_client = AsyncOpaClient(url=SETTINGS.opa_url, client=httpx_client)
    return await ProxyService.create(
        request=request,
        dao=dao,
        balancing_factory=balancing_factory,
        httpx_client=httpx_client,
        opa_client=opa_client,
        cache=cache,
    )
