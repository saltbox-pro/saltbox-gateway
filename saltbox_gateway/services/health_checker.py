import asyncio
import time
from typing import Annotated

import httpx
from fastapi import Depends
from redis.asyncio import Redis

from saltbox_gateway.config import SETTINGS, logger
from saltbox_gateway.dao.service_dao import ServiceDAO, get_service_dao
from saltbox_gateway.utils.httpx_client import HttpxClientSingletoneFactory
from saltbox_gateway.utils.redis_config import get_redis, get_redis_connection
from saltbox_gateway.utils.redis_locker import AsyncRedisLockerFactory
from saltbox_sdk.discovery_client.schemas import ServiceInstance, ServiceSchema


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
        self.running = True
        await self._health_check_loop()

    async def stop(self) -> None:
        """Stop the health checker service."""
        self.running = False

    async def _health_check_loop(self) -> None:
        """Main loop for periodic health checks."""
        while self.running:
            try:
                await self._check_all_services()
            except Exception as e:
                logger.error(f'Health check failed: {e}')
            await asyncio.sleep(SETTINGS.app.health_check_interval)

    async def _check_all_services(self) -> None:
        services_data = await self._dao.list()
        if not services_data:
            logger.info('No services registered for health check')
            return

        services = [ServiceSchema(**service.get('data', {})) for service in services_data]
        await asyncio.gather(*(self._check_service_instances(service) for service in services))

    async def _check_service_instances(self, service: ServiceSchema) -> None:
        async def check_instance(instance: ServiceInstance) -> ServiceInstance:
            url = f'http://{instance.host}:{instance.port}{instance.healthcheck_path}'
            try:
                response = await self._httpx_client.get(url, timeout=SETTINGS.app.health_check_timeout)
                if response.status_code == 200:
                    instance.healthy = True
                    instance.last_check = instance.last_healthy = time.time()
                else:
                    logger.warning(
                        f'Service {service.name} instance {instance.host}:{instance.port} unhealthy: '
                        f'HTTP {response.status_code}'
                    )
                    instance.healthy = False
                    instance.last_check = time.time()
            except Exception as e:
                logger.error(
                    f'Service {service.name} instance {instance.host}:{instance.port} health check failed: {e}'
                )
                instance.healthy = False
                instance.last_check = time.time()

            return instance

        task_results = await asyncio.gather(
            *(check_instance(instance) for instance in service.instances), return_exceptions=True
        )

        updated_instances = [inst for inst in task_results if isinstance(inst, ServiceInstance)]

        service.instances = updated_instances
        service.front_config.is_available = any(inst.healthy for inst in updated_instances)

        async with self._locker.create(key=service.name):
            await self._dao.update(service.model_dump())


def get_health_checker_service() -> HealthChecker:
    """Get the HealthChecker service instance."""
    redis_client = get_redis_connection()
    dao = get_service_dao(redis_client)
    locker_factory = AsyncRedisLockerFactory(redis_client=redis_client)
    httpx_client = HttpxClientSingletoneFactory.get_instance()
    return HealthChecker(dao=dao, locker_factory=locker_factory, httpx_client=httpx_client)


def get_health_checker(
    dao: Annotated[ServiceDAO, Depends(get_service_dao)],
    redis_client: Annotated[Redis, Depends(get_redis)],
) -> HealthChecker:
    """Dependency to get the HealthChecker instance."""
    locker_factory = AsyncRedisLockerFactory(redis_client=redis_client)
    httpx_client = HttpxClientSingletoneFactory.get_instance()
    return HealthChecker(dao, locker_factory, httpx_client)
