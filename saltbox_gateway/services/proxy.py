import base64
import json
from collections.abc import Callable
from typing import Annotated

import httpx
from fastapi import Depends, Request
from redis.asyncio import Redis

from saltbox_gateway.config import SETTINGS, logger
from saltbox_gateway.dao.service_dao import ServiceDAO, get_service_dao
from saltbox_gateway.errors import NoHealthyInstanceError, ServiceDisabledError
from saltbox_gateway.schemas import ServiceEndpoint, ServiceInstance, ServiceSchema
from saltbox_gateway.utils.balancing_strategies import BalancingStrategy, balancing_strategy_factory
from saltbox_gateway.utils.httpx_client import HttpxClientSingletoneFactory
from saltbox_gateway.utils.redis_cache import BaseCache, CustomRedisCache
from saltbox_gateway.utils.redis_config import get_redis


class ProxyService:
    def __init__(
        self,
        request: Request,
        dao: ServiceDAO,
        balancing_factory: Callable[[str], BalancingStrategy],
        httpx_client: httpx.AsyncClient | None = None,
        cache: BaseCache | None = None,
    ) -> None:
        self._request = request
        self._dao = dao
        self._balancing_factory = balancing_factory
        self._httpx_client = httpx_client or httpx.AsyncClient(timeout=SETTINGS.proxy_request_timeout)
        self._cache = cache

    async def proxy_request(
        self,
        service_name: str,
        path: str,
    ) -> httpx.Response:
        """Proxy a request to a service instance."""
        logger.debug(f'Proxying request to service: {service_name}, path: {path}, method: {self._request.method}')
        service_data = await self._dao.get(service_name)

        service = ServiceSchema(**service_data.get('data', {}))

        if not service.enabled:
            raise ServiceDisabledError(service.service_name)

        instance = await self._get_instance(service)

        # TODO: Add base_url to the path
        url = f'http://{instance.host}:{instance.port}/{path.lstrip("/")}'
        logger.debug(f'Using instance: {instance.host}, URL: {url}')

        request_params = await self._get_request_params()

        endpoint_config = await self._get_endpoint_config(service, request_params['method'], path)
        logger.debug(f'Using endpoint config: {endpoint_config}')

        cache_key = f'{service_name}:{path}:{request_params["method"]}:{request_params.get("params", "")!s}'
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

    async def _get_endpoint_config(self, service: ServiceSchema, method: str, path: str) -> ServiceEndpoint:
        """Get the endpoint configuration for a service."""
        if not service or not service.endpoints:
            return ServiceEndpoint(method=method, path=path)

        for endpoint in service.endpoints:
            if endpoint.method.lower() == method.lower() and endpoint.path.strip('/') == path.strip('/'):
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

        if method in ['POST', 'PUT', 'PATCH']:
            kwargs['content'] = await self._request.body()

        return {
            'method': method,
            **kwargs,
        }

    async def _get_instance(self, service: ServiceSchema) -> ServiceInstance:
        healthy_instances = [inst for inst in service.instances if inst.healthy]
        logger.debug(f'Healthy instances for service "{service.service_name}": {healthy_instances}')

        if not healthy_instances:
            raise NoHealthyInstanceError(service.service_name)

        strategy = self._balancing_factory(service.balancing_strategy)

        return await strategy.choose(service.service_name, healthy_instances)


def get_proxy_service(
    request: Request,
    dao: Annotated[ServiceDAO, Depends(get_service_dao)],
    redis_client: Annotated[Redis, Depends(get_redis)],
) -> ProxyService:
    httpx_client = HttpxClientSingletoneFactory.get_instance()
    balancing_factory = balancing_strategy_factory(redis_client)
    cache = CustomRedisCache(redis_client=redis_client, namespace='gate_cache')
    return ProxyService(
        request=request,
        dao=dao,
        balancing_factory=balancing_factory,
        httpx_client=httpx_client,
        cache=cache,
    )
