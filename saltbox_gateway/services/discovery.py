from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis

from saltbox_gateway.config import SETTINGS, logger
from saltbox_gateway.dao.service_dao import ServiceDAO, get_service_dao
from saltbox_gateway.exceptions import (
    NonOfficialServiceException,
    ServiceAlreadyExistsException,
    ServiceInstanceNotFoundException,
    ServiceNotFoundException,
)
from saltbox_gateway.schemas import (
    DiscoveryServiceConfig,
    KeycloakConfig,
)
from saltbox_gateway.utils.redis_config import get_redis
from saltbox_gateway.utils.redis_locker import AsyncRedisLockerFactory
from saltbox_sdk.config.keycloak_config import KC_SETTINGS
from saltbox_sdk.discovery_client.schemas import (
    ProxyBalancingStrategy,
    ServiceInstance,
    ServiceSchema,
    ServiceType,
)


class DiscoveryService:
    """Service for managing discovery operations."""

    def __init__(self, dao: ServiceDAO, locker: AsyncRedisLockerFactory) -> None:
        self._dao = dao
        self._locker = locker

    def _to_service_schema(self, service_data: dict) -> ServiceSchema:
        """Convert raw service data to ServiceSchema."""
        return ServiceSchema(**service_data.get('data', {}))

    async def process(self, service: ServiceSchema) -> ServiceSchema:
        if service.type == ServiceType.OFFICIAL:
            if service.name not in SETTINGS.app.official_modules:
                raise NonOfficialServiceException(service.name)

        logger.debug(f'Try to register service: {service.name}')

        async with self._locker.create(key=service.name):
            try:
                created_data = await self._dao.create(service.model_dump())
            except ServiceAlreadyExistsException as e:
                logger.debug(f'Service already exists: {e.service_name}\nTrying to update with new instances...')
                existing_service_data = await self._dao.get(service.name)

                existing_service = ServiceSchema(**existing_service_data.get('data', {}))
                # updated_service = await self._add_instance_to_service(existing_service, service.instances)
                updated_instances = await self._merge_instances(existing_service.instances, service.instances)
                updated_service = service.model_copy(update={'instances': updated_instances})

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

    async def remove_service_instance(self, service_name: str, id: str) -> None:
        """Remove service instance by uuid."""
        async with self._locker.create(key=service_name):
            service_data = await self._dao.get(service_name)

            instances = service_data.get('data', {}).get('instances', [])
            updated_instances = [inst for inst in instances if not (inst['id'] == id)]

            if len(updated_instances) == len(instances):
                raise ServiceInstanceNotFoundException(service_name=service_name, instance_id=id)

            updated_service = service_data.get('data', {})
            updated_service['instances'] = updated_instances

            await self._dao.update(updated_service)

    async def _merge_instances(
        self, current_instances: list[ServiceInstance], new_instances: list[ServiceInstance]
    ) -> list[ServiceInstance]:
        merged_instances = {inst.id: inst for inst in current_instances}
        for instance in new_instances:
            merged_instances[instance.id] = instance

        return list(merged_instances.values())

    async def toggle_service(self, service_name: str, enable: bool) -> ServiceSchema:
        """Enable or disable a service."""
        async with self._locker.create(key=service_name):
            service = await self.get_service_by_name(service_name)

            if not service:
                raise ServiceNotFoundException(service_name)

            updated_data = service.model_copy(update={'enabled': enable})
            updated_service = await self._dao.update(updated_data.model_dump())

        return self._to_service_schema(updated_service)

    async def change_balancing_strategy(self, service_name: str, strategy: ProxyBalancingStrategy) -> ServiceSchema:
        """Change the balancing strategy for a service."""
        async with self._locker.create(key=service_name):
            service = await self.get_service_by_name(service_name)

            if service.load_balancing_strategy == strategy:
                return service

            updated_data = service.model_copy(update={'balancing_strategy': strategy})
            updated_service = await self._dao.update(updated_data.model_dump())
        return self._to_service_schema(updated_service)

    async def get_config(self) -> DiscoveryServiceConfig:
        services = await self.get_all_services()

        config = DiscoveryServiceConfig(
            auth_config=KeycloakConfig(
                authority=f'{KC_SETTINGS.front_url}/realms/{KC_SETTINGS.realm}',
                client_id=KC_SETTINGS.client,
                redirect_uri=f'{SETTINGS.app.server_scheme}://{SETTINGS.app.server_outer_socket}',
                client_secret=KC_SETTINGS.client_secret,
            ),
            services=[service.front_config for service in services if service.enabled],
        )

        return config


def get_discovery_service(
    dao: Annotated[ServiceDAO, Depends(get_service_dao)],
    redis_client: Annotated[Redis, Depends(get_redis)],
) -> DiscoveryService:
    locker_factory = AsyncRedisLockerFactory(redis_client=redis_client)
    return DiscoveryService(dao, locker_factory)
