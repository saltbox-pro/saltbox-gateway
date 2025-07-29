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
    NotEnoughPermissionsError,
    ProxyOpaClientInitializationError,
    ProxyStaticFileError,
    ServiceDisabledError,
    ServiceHasNoHealthyInstancesError,
)
from saltbox_gateway.schemas import User
from saltbox_gateway.utils.balancing_strategies import BalancingStrategy, balancing_strategy_factory
from saltbox_gateway.utils.httpx_client import HttpxClientSingletoneFactory
from saltbox_gateway.utils.opa_client import AsyncOpaClient
from saltbox_gateway.utils.redis_cache import BaseCache, CustomRedisCache
from saltbox_gateway.utils.redis_config import get_redis
from saltbox_sdk.discovery_client.schemas import OPAConfig, ServiceEndpoint, ServiceInstance, ServiceSchema


class ProxyService:
    def __init__(
        self,
        request: Request,
        dao: ServiceDAO,
        balancing_factory: Callable[[str], BalancingStrategy],
        httpx_client: httpx.AsyncClient | None = None,
        opa_client: AsyncOpaClient | None = None,
        cache: BaseCache | None = None,
    ) -> None:
        self._request = request
        self._dao = dao
        self._balancing_factory = balancing_factory
        self._httpx_client = httpx_client or httpx.AsyncClient(timeout=SETTINGS.proxy_request_timeout)
        self._opa_client = opa_client
        self._cache = cache

    # TODO: Refactor this
    async def proxy_request(  # noqa: C901
        self,
        service_name: str,
        path: str,
    ) -> httpx.Response:
        """Proxy a request to a service instance."""
        logger.debug(f'Proxying request to service: {service_name}, path: {path}, method: {self._request.method}')
        service_data = await self._dao.get(service_name)

        service = ServiceSchema(**service_data.get('data', {}))

        if not service.enabled:
            raise ServiceDisabledError(service.name)

        instance = await self._choose_healthy_instance(service)

        url = f'http://{instance.host}:{instance.port}/{path.lstrip("/")}'
        logger.debug(f'Using instance: {instance.host}, URL: {url}')

        request_params = await self._get_request_params()

        endpoint_config = await self._get_endpoint_config(instance, request_params['method'], path)
        logger.debug(f'Using endpoint config: {endpoint_config}')
        if not hasattr(self._request.state, 'user'):
            user_id = 'anonymous'
        else:
            user_id = self._request.state.user.get('sub', 'anonymous')

        cache_key = f'{user_id}:{service_name}:{path}:{request_params["method"]}:{request_params.get("params", "")!s}'
        response_data = None

        if endpoint_config.cache_ttl and self._cache:
            response_data = await self._cache.get(cache_key)
            if response_data:
                if isinstance(response_data, bytes | str):
                    if isinstance(response_data, bytes):
                        response_data = response_data.decode('utf-8')
                    response_data = json.loads(response_data)
                logger.debug(f'Cache hit for key: {cache_key}')
                return httpx.Response(
                    status_code=response_data['status_code'],
                    headers=response_data['headers'],
                    content=base64.b64decode(response_data['content']),
                )
            logger.debug(f'Cache miss for key: {cache_key}, forwarding request')

        if self._opa_client and endpoint_config.opa_config.policy and endpoint_config.opa_config.policy != 'public':
            opa_response = await self._check_opa_policy(
                endpoint_config.opa_config,
                request_params['method'],
                path,
            )

            logger.debug(f'OPA response: {opa_response}')

            if not opa_response.get('allow', False):
                raise NotEnoughPermissionsError(service_name=service.name, path=path)

            request_params['headers']['X-OPA-Result'] = json.dumps(opa_response)
            query_value = opa_response.get('query', '')
            if isinstance(query_value, dict):
                query_value = json.dumps(query_value)
            request_params['params']['opa_query'] = query_value

        resp = await self._httpx_client.request(
            request_params['method'],
            url,
            headers=request_params['headers'],
            params=request_params['params'],
            content=request_params.get('content', None),
        )

        if endpoint_config.cache_ttl and self._cache and resp.status_code == 200:
            logger.debug(f'Storing response in cache for key: {cache_key} with TTL: {endpoint_config.cache_ttl}')
            await self._cache.set(
                cache_key,
                {
                    'status_code': resp.status_code,
                    'headers': dict(resp.headers),
                    'content': base64.b64encode(resp.content).decode('ascii'),
                },
                ttl=endpoint_config.cache_ttl,
            )

        return resp

    async def _check_opa_policy(self, opa_config: OPAConfig, method: str, path: str) -> dict:
        """Check OPA policy for the given method and path."""
        if not self._opa_client:
            raise ProxyOpaClientInitializationError()

        input_data = {
            'request': {
                'method': method.upper(),
                'path': path.strip('/').split('/'),
            },
            'user': User(**self._request.state.user).model_dump(),
        }

        if opa_config.is_partial and opa_config.partial_query:
            # For partial compile, we need to provide the query and unknowns
            logger.debug('Partial OPA compile request')
            response = await self._opa_client.compile(
                package=opa_config.policy,
                input=input_data,
                unknowns=opa_config.unknowns or [],
                partial_query=opa_config.partial_query,
                query_filter_format=opa_config.query_filter_format,
            )
            return response

        logger.debug('Full OPA check policy request')
        # For full policy check, we just need to check the policy
        try:
            response = await self._opa_client.check_policy(
                package=opa_config.policy,
                input=input_data,
            )
            return response
        except Exception as e:
            logger.error(f'OPA policy check failed: {e}')
            return {}

    @staticmethod
    def _path_to_regex(endpoint_path: str) -> re.Pattern:
        regex = re.sub(r'{[^/]+}', r'[^/]+', endpoint_path.strip('/'))
        return re.compile(f'^{regex}$')

    async def _get_endpoint_config(self, instance: ServiceInstance, method: str, path: str) -> ServiceEndpoint:
        """Get the endpoint configuration for a service."""
        if not instance or not instance.endpoints:
            return ServiceEndpoint(method=method, path=path)

        request_path = path.strip('/')

        for endpoint in instance.endpoints:
            if endpoint.method.lower() == method.lower():
                pattern = self._path_to_regex(endpoint.path)
                if pattern.match(request_path):
                    return endpoint

        return ServiceEndpoint(method=method, path=path)

    # TODO: Need to refactor this method to use a more structured way of handling request parameters
    async def _get_request_params(self) -> dict:
        method = self._request.method
        headers = dict(self._request.headers)
        params = dict(self._request.query_params)

        headers.pop('host', None)
        headers.pop('content-length', None)

        kwargs: dict[str, dict | bytes] = {'headers': headers, 'params': params}

        if method in ['POST', 'PUT', 'PATCH', 'DELETE']:
            kwargs['content'] = await self._request.body()

        return {
            'method': method,
            **kwargs,
        }

    async def _choose_healthy_instance(self, service: ServiceSchema) -> ServiceInstance:
        healthy_instances = [inst for inst in service.instances if inst.healthy]

        if not healthy_instances:
            raise ServiceHasNoHealthyInstancesError(service.name)

        strategy = self._balancing_factory(service.load_balancing_strategy)

        return await strategy.choose(service.name, healthy_instances)

    async def proxy_static(
        self,
        service_name: str,
        path: str,
    ) -> httpx.Response:
        """Proxy a static file request to a service frontend Nginx."""

        service_data = await self._dao.get(service_name)
        service = ServiceSchema(**service_data.get('data', {}))

        if not service.front_config.static_host:
            raise ProxyStaticFileError(message=f'Static host is not configured for service `{service.name}`.')
        url = f'{service.front_config.static_host}/{path.lstrip("/")}'
        logger.debug(f'Proxy static to: {url}')
        request_params = await self._get_request_params()
        try:
            resp = await self._httpx_client.request(
                request_params['method'],
                url,
                headers=request_params['headers'],
                params=request_params['params'],
                content=request_params.get('content', None),
            )

            return httpx.Response(
                status_code=resp.status_code,
                headers=dict(resp.headers),
                content=await resp.aread(),
            )
        except Exception as e:
            raise ProxyStaticFileError(message=str(e)) from e


def get_proxy_service(
    request: Request,
    dao: Annotated[ServiceDAO, Depends(get_service_dao)],
    redis_client: Annotated[Redis, Depends(get_redis)],
) -> ProxyService:
    httpx_client = HttpxClientSingletoneFactory.get_instance()
    balancing_factory = balancing_strategy_factory(redis_client)
    cache = CustomRedisCache(redis_client=redis_client, namespace='gate_cache')
    opa_client = AsyncOpaClient(url=SETTINGS.opa_url, client=httpx_client)
    return ProxyService(
        request=request,
        dao=dao,
        balancing_factory=balancing_factory,
        httpx_client=httpx_client,
        opa_client=opa_client,
        cache=cache,
    )
