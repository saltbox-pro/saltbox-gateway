from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis

from saltbox_gateway.config import SETTINGS, logger
from saltbox_gateway.dao.service_dao import ServiceDAO, get_service_dao
from saltbox_gateway.errors import (
    ServiceAlreadyExistsError,
    ServiceIsNotOfficial,
    ServiceNotFoundError,
)
from saltbox_gateway.schemas import ProxyBalancingStrategy, ServiceInstance, ServiceSchema, ServiceType
from saltbox_gateway.utils.redis_config import get_redis
from saltbox_gateway.utils.redis_locker import AsyncRedisLockerFactory


class DiscoveryService:
    """Service for managing discovery operations."""

    def __init__(self, dao: ServiceDAO, locker: AsyncRedisLockerFactory) -> None:
        self._dao = dao
        self._locker = locker

    def _to_service_schema(self, service_data: dict) -> ServiceSchema:
        """Convert raw service data to ServiceSchema."""
        return ServiceSchema(**service_data.get('data', {}))

    async def process(self, service: ServiceSchema) -> ServiceSchema:
        if service.service_type == ServiceType.OFFICIAL:
            if service.service_name not in SETTINGS.official_modules:
                raise ServiceIsNotOfficial(service.service_name)

        logger.debug(f'Try to register service: {service.service_name}')

        async with self._locker.create(key=service.service_name):
            try:
                created_data = await self._dao.create(service.model_dump())
            except ServiceAlreadyExistsError as e:
                logger.debug(f'Service already exists: {e.service_name}\nTrying to update with new instances...')
                existing_service_data = await self._dao.get(service.service_name)

                existing_service = ServiceSchema(**existing_service_data.get('data', {}))
                updated_service = await self._add_instance_to_service(existing_service, service.instances)

                created_data = await self._dao.update(updated_service.model_dump())

        return self._to_service_schema(created_data)

    async def get_service_by_name(self, service_name: str) -> ServiceSchema:
        """Get a service by its name."""
        service_data = await self._dao.get(service_name)
        return self._to_service_schema(service_data)

    async def get_all_services(self) -> list[ServiceSchema]:
        """Get all registered services."""
        services_data = await self._dao.list()

        return [self._to_service_schema(service) for service in services_data]

    async def remove_service(self, service_name: str) -> None:
        """Remove a service by its name."""
        async with self._locker.create(key=service_name):
            return await self._dao.delete(service_name)

    async def remove_service_instance(self, service_name: str, host: str, port: int) -> None:
        """Remove a specific service instance."""
        async with self._locker.create(key=service_name):
            service_data = await self._dao.get(service_name)

            instances = service_data.get('data', {}).get('instances', [])
            updated_instances = [inst for inst in instances if not (inst['host'] == host and inst['port'] == port)]

            if len(updated_instances) == len(instances):
                msg = f'Instance {host}:{port} not found in service {service_name}'
                # TODO: change exception type to ServiceInstanceNotFoundError
                raise ServiceNotFoundError(msg)

            updated_service = service_data.get('data', {})
            updated_service['instances'] = updated_instances

            await self._dao.update(updated_service)

    async def _add_instance_to_service(self, service: ServiceSchema, instances: list[ServiceInstance]) -> ServiceSchema:
        """Add instances to a service, merging with existing instances."""
        logger.debug(f'Adding instances to service: {service.service_name}')

        # Use (host, port) as the unique key for each instance
        merged_instances = {(inst.host, inst.port): inst for inst in service.instances}
        for instance in instances:
            merged_instances[(instance.host, instance.port)] = instance

        updated_service = service.model_copy(update={'instances': list(merged_instances.values())})
        return updated_service

    async def toggle_service(self, service_name: str, enable: bool) -> ServiceSchema:
        """Enable or disable a service."""
        async with self._locker.create(key=service_name):
            service = await self.get_service_by_name(service_name)

            if not service:
                raise ServiceNotFoundError(service_name)

            updated_data = service.model_copy(update={'enabled': enable})
            updated_service = await self._dao.update(updated_data.model_dump())

        return self._to_service_schema(updated_service)

    async def change_balancing_strategy(self, service_name: str, strategy: ProxyBalancingStrategy) -> ServiceSchema:
        """Change the balancing strategy for a service."""
        async with self._locker.create(key=service_name):
            service = await self.get_service_by_name(service_name)

            if service.balancing_strategy == strategy:
                return service

            updated_data = service.model_copy(update={'balancing_strategy': strategy})
            updated_service = await self._dao.update(updated_data.model_dump())
        return self._to_service_schema(updated_service)


def get_discovery_service(
    dao: Annotated[ServiceDAO, Depends(get_service_dao)],
    redis_client: Annotated[Redis, Depends(get_redis)],
) -> DiscoveryService:
    locker_factory = AsyncRedisLockerFactory(redis_client=redis_client)
    return DiscoveryService(dao, locker_factory)
