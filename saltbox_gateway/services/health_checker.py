import asyncio
import time
from typing import Annotated

import httpx
from fastapi import Depends
from redis.asyncio import Redis

from saltbox_gateway.config import SETTINGS, logger
from saltbox_gateway.dao.service_dao import ServiceDAO, get_service_dao
from saltbox_gateway.schemas import ServiceEndpoint, ServiceInstance, ServiceSchema
from saltbox_gateway.utils.httpx_client import HttpxClientSingletoneFactory
from saltbox_gateway.utils.redis_config import get_redis, get_redis_connection
from saltbox_gateway.utils.redis_locker import AsyncRedisLockerFactory


class HealthChecker:
    def __init__(
        self, dao: ServiceDAO, locker_factory: AsyncRedisLockerFactory, httpx_client: httpx.AsyncClient
    ) -> None:
        self._dao = dao
        self._locker = locker_factory
        self._httpx_client = httpx_client
        self.running = False

    async def start(self) -> None:
        """Start the health checker service."""
        # Implementation for starting the health checker service with asyncio
        self.running = True
        await self._health_check_loop()

    async def stop(self) -> None:
        """Stop the health checker service."""
        self.running = False
        # Implementation for stopping the health checker service

    async def _health_check_loop(self) -> None:
        """Main loop for periodic health checks."""
        while self.running:
            try:
                await self._check_all_services()
            except Exception as e:
                logger.error(f'Health check failed: {e}')
            await asyncio.sleep(SETTINGS.health_check_interval)

    async def _check_all_services(self) -> None:
        services_data = await self._dao.list()
        if not services_data:
            logger.info('No services registered for health check')
            return

        logger.info(f'Checking health for {len(services_data)} services')
        services = [ServiceSchema(**service.get('data', {})) for service in services_data]
        await asyncio.gather(*(self._check_service_instances(service) for service in services))

    async def _check_service_instances(self, service: ServiceSchema) -> None:
        async def check_instance(instance: ServiceInstance, health_path: str = '/health') -> ServiceInstance:
            url = f'http://{instance.host}:{instance.port}{health_path}'
            try:
                response = await self._httpx_client.get(url, timeout=SETTINGS.health_check_timeout)
                if response.status_code == 200:
                    logger.info(f'Service {service.service_name} instance {instance.host}:{instance.port} is healthy')
                    instance.healthy = True
                    instance.last_check = instance.last_healthy = time.time()
                else:
                    logger.warning(
                        f'Service {service.service_name} instance {instance.host}:{instance.port} unhealthy: '
                        f'HTTP {response.status_code}'
                    )
                    instance.healthy = False
                    instance.last_check = time.time()
            except Exception as e:
                logger.error(
                    f'Service {service.service_name} instance {instance.host}:{instance.port} health check failed: {e}'
                )
                instance.healthy = False
                instance.last_check = time.time()

            return instance

        task_results = await asyncio.gather(
            *(check_instance(instance) for instance in service.instances), return_exceptions=True
        )

        updated_instances = [inst for inst in task_results if isinstance(inst, ServiceInstance)]

        service.instances = updated_instances

        # Try to discover endpoints for all instances
        # if service.auto_discover_routes:
        #     logger.info(f'Discovering endpoints for service {service.service_name}')
        #     endpoints = []
        #     for inst in (inst for inst in service.instances if inst.healthy):
        #         endpoints = await self._discover_endpoints(inst)
        #         logger.debug(f'Discovered endpoints for {inst.host}:{inst.port}: {endpoints}')
        #         if endpoints:
        #             break
        #     service.endpoints = endpoints

        first_healthy = next((inst for inst in service.instances if inst.healthy), None)
        if first_healthy and service.auto_discover_routes:
            logger.info(f'Discovering endpoints for service {service.service_name}')
            discovered_endpoints = await self._discover_endpoints(first_healthy)
            logger.debug(f'Discovered {len(discovered_endpoints)} endpoints for {service.service_name}')
            if discovered_endpoints:
                service.endpoints = discovered_endpoints
        else:
            logger.info(f'No healthy instances found for service {service.service_name}, skipping endpoint discovery')

        async with self._locker.create(key=service.service_name):
            await self._dao.update(service.model_dump())

    async def _discover_endpoints(self, instance: ServiceInstance) -> list[ServiceEndpoint]:
        """Discover endpoints for a service instance."""
        base_route = f'/{instance.base_route.strip("/")}' if instance.base_route else ''
        url = f'http://{instance.host}:{instance.port}{base_route}/openapi-routes'
        response = await self._httpx_client.get(url, timeout=SETTINGS.proxy_request_timeout)
        if response.status_code == 200:
            routes_data = response.json()
            if 'endpoints' in routes_data:
                return [ServiceEndpoint(**endpoint) for endpoint in routes_data['endpoints']]
        return []


def get_health_checker_service() -> HealthChecker:
    """Get the HealthChecker service instance."""
    redis_client = get_redis_connection()
    logger.debug(f'Using Redis client: {redis_client}')
    dao = get_service_dao(redis_client)
    logger.debug(f'Using ServiceDAO: {dao}')
    return HealthChecker(
        dao, AsyncRedisLockerFactory(redis_client=redis_client), HttpxClientSingletoneFactory.get_instance()
    )


def get_health_checker(
    dao: Annotated[ServiceDAO, Depends(get_service_dao)],
    redis_client: Annotated[Redis, Depends(get_redis)],
) -> HealthChecker:
    """Dependency to get the HealthChecker instance."""
    locker_factory = AsyncRedisLockerFactory(redis_client=redis_client)
    httpx_client = HttpxClientSingletoneFactory.get_instance()
    return HealthChecker(dao, locker_factory, httpx_client)
