import base64
import json
import re
from collections.abc import Callable
from typing import Annotated

import httpx
from fastapi import Depends, Request
from redis.asyncio import Redis

from saltbox_gateway.config import SETTINGS, logger
from saltbox_gateway.dao.service_dao import ServiceDAO, get_service_dao
from saltbox_gateway.errors import (
    ApiProxyRequestError,
    NotEnoughPermissionsError,
    # ProxyOpaClientInitializationError,
    ProxyStaticFileError,
    ServiceDisabledError,
    ServiceEndpointNotFoundError,
    ServiceHasNoEndpointsError,
    ServiceHasNoHealthyInstancesError,
    ServiceHasNoInstancesError,
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
        if request.method in ['POST', 'PUT', 'PATCH', 'DELETE']:
            raw_body = await request.body()
            body = None
            if request.headers.get('content-type', '').startswith('application/json'):
                try:
                    body = json.loads(raw_body)
                except Exception:
                    body = None
        request_data = ProxyRequestData(
            method=request.method.upper(),
            path=request.url.path.strip('/'),
            query_params=dict(request.query_params),
            headers=dict(request.headers),
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
        logger.debug(f'NEW Processing request for service: {service_name}, path: {path}')
        service = await self._get_service(service_name)

        service_instance = await self._choose_healthy_instance(service)
        if not service_instance.endpoints:
            raise ServiceHasNoEndpointsError(service.name)

        endpoint = await self._get_endpoint(service_instance.endpoints, path)

        if not endpoint:
            logger.debug(f'No endpoint found for service: {service_name}, path: {path}')
            if path.startswith('docs') or path.startswith('openapi'):
                endpoint = ServiceEndpoint(
                    path=path,
                    method=self._request_data.method,
                    opa_config=OPAConfig(
                        policy='public',
                        is_partial=False,
                        query_filter_format=None,
                    ),
                    cache_ttl=0,  # Disable caching for docs
                )
            else:
                raise ServiceEndpointNotFoundError(service.name, path)

        url = f'http://{service_instance.host}:{service_instance.port}/{path.lstrip("/")}'

        # TODO: refactor cache conditions
        if endpoint.cache_ttl > 0:
            cached_response = await self._get_response_from_cache()
            if cached_response:
                return cached_response

        service_response = await self._get_response_from_service(url)

        if endpoint.cache_ttl > 0 and self._is_response_cachable(service_response):
            await self._add_response_to_cache(service_response, endpoint.cache_ttl)

        return service_response

    async def _check_access(
        self, opa_config: OPAConfig, service_name: str, path: str, service_response: httpx.Response
    ) -> None:
        # компайл только для гет-запросов? Как разделить запросы к OPA для частичного и полного запроса?
        if (
            opa_config.policy
            and opa_config.policy != 'public'
            and opa_config.is_partial
            and opa_config.partial_query is not None
        ):
            input_data = await self._prepare_input_for_opa(service_name, path)

            opa_response = await self._opa_client.check_access(
                package=opa_config.policy,
                input=input_data,
                is_partial=True,
                unknowns=opa_config.unknowns or [],
                partial_query=opa_config.partial_query,
                query_filter_format=opa_config.query_filter_format,
            )
            if not opa_response.get('allow', False):
                raise NotEnoughPermissionsError(service_name=service_name, path=path)

            if opa_response.get('query') is not None:
                self._request_data.query_params.update({'opa_query': opa_response['query']})

        # if opa_config is not partial - check access for full query
        if opa_config.policy and opa_config.policy != 'public' and not opa_config.is_partial:
            try:
                json_data = service_response.json().get('data', None)
            except json.JSONDecodeError:
                json_data = {}
            input_data = await self._prepare_input_for_opa(service_name, path, object=json_data)
            opa_response = await self._opa_client.check_access(
                package=opa_config.policy,
                input=input_data,
                is_partial=False,
            )

    async def _prepare_input_for_opa(self, service_name: str, path: str, object: dict | None = None) -> dict:
        return {
            'subject': self._request_data.user.model_dump(),
            'action': {
                'method': self._request_data.method,
            },
            'resource': {
                'service_name': service_name,
                'path': path.strip('/').split('/'),
                'query_params': self._request_data.query_params,
                'object': object,
                'body': self._request_data.body,
            },
        }

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
            if isinstance(cached_response, bytes | str):
                if isinstance(cached_response, bytes):
                    cached_response = cached_response.decode('utf-8')
                cached_response = json.loads(cached_response)
            logger.debug(f'Cache hit for key: {self._request_data.cache_key}')
            return httpx.Response(
                status_code=cached_response['status_code'],
                headers=cached_response['headers'],
                content=base64.b64decode(cached_response['content']),
            )
        logger.debug(f'Cache miss for key: {self._request_data.cache_key}')
        return None

    async def _get_response_from_service(self, url: str) -> httpx.Response:
        response = await self._httpx_client.request(
            self._request_data.method,
            url,
            headers=self._request_data.headers,
            params=self._request_data.query_params,
            content=self._request_data.raw_body,
            follow_redirects=True,
        )
        if not response.is_success:
            detail = 'Unknown error occurred while processing the request.'
            if response.content and response.headers.get('content-type', '').startswith('application/json'):
                try:
                    detail = response.json().get('detail', detail)
                except Exception as e:
                    logger.warning(f'Ошибка парсинга JSON из ответа сервиса: {e}')
            raise ApiProxyRequestError(
                status_code=response.status_code,
                message=detail,
            )

        return response

    async def proxy_static_file(self, service_name: str, path: str) -> httpx.Response:
        service = await self._get_service(service_name)
        if not service.front_config.static_host:
            raise ProxyStaticFileError(message=f'Static host is not configured for service `{service.name}`.')
        url = f'{service.front_config.static_host}/{path.lstrip("/")}'

        logger.debug(f'Fetching static file from {url}')

        static_response = await self._httpx_client.get(
            url,
            headers=self._request_data.headers,
            params=self._request_data.query_params,
        )

        if static_response.status_code != 200:
            raise ProxyStaticFileError(
                message=f'Failed to fetch static file from `{url}`. Status code: {static_response.status_code}'
            )

        return static_response

    async def _get_service(self, service_name: str) -> ServiceSchema:
        service_data = await self._dao.get(service_name)

        service = ServiceSchema(**service_data.get('data', {}))

        if not service.enabled:
            raise ServiceDisabledError(service.name)

        if not service.instances:
            raise ServiceHasNoInstancesError(service.name)

        return service

    async def _choose_healthy_instance(self, service: ServiceSchema) -> ServiceInstance:
        healthy_instances = [inst for inst in service.instances if inst.healthy]

        if not healthy_instances:
            raise ServiceHasNoHealthyInstancesError(service.name)

        strategy = self._balancing_factory(service.load_balancing_strategy)

        return await strategy.choose(service.name, healthy_instances)

    @staticmethod
    def _path_to_regex(endpoint_path: str) -> re.Pattern:
        regex = re.sub(r'{[^/]+}', r'[^/]+', endpoint_path.strip('/'))
        return re.compile(f'^{regex}$')

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
