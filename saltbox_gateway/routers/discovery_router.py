from typing import Annotated

from fastapi import APIRouter, Body, Depends
from redis.asyncio import Redis

from saltbox_gateway.config import logger
from saltbox_gateway.exceptions import DiscoveryServiceException
from saltbox_gateway.schemas import (
    DiscoveryServiceConfig,
)
from saltbox_gateway.services.discovery import DiscoveryService, get_discovery_service
from saltbox_sdk.db.redis.config import get_redis
from saltbox_sdk.discovery_client.schemas import (
    DiscoveryResponse,
    ProxyBalancingStrategy,
    ServiceFrontendConfig,
    ServiceSchema,
)

router = APIRouter(prefix='/api/discovery', tags=['Discovery'])


@router.get('/health')
async def health_check(
    redis: Annotated[Redis, Depends(get_redis)],
) -> dict:
    """Health check для API Gateway"""
    try:
        pong = await redis.ping()
        return {'status': 'healthy', 'service': 'api-gateway', 'redis': pong}
    except Exception:
        raise DiscoveryServiceException() from None


@router.get('/config', response_model_exclude={'services': {'__all__': {'static_host'}}})
async def get_full_config(
    discovery_service: Annotated[DiscoveryService, Depends(get_discovery_service)],
) -> DiscoveryServiceConfig:
    """Get full configuration for the frontend."""
    config = await discovery_service.get_config()
    return config


@router.post('/add-standalone-front')
async def add_standalone_front(
    data: ServiceFrontendConfig,
    discovery_service: Annotated[DiscoveryService, Depends(get_discovery_service)],
) -> dict:
    """Get full configuration for the frontend."""
    result = await discovery_service.add_standalone_front(data)
    return result


@router.post('/register')
async def register_service(
    service_info: ServiceSchema,
    discovery_service: Annotated[DiscoveryService, Depends(get_discovery_service)],
) -> DiscoveryResponse:
    """Register a new service in the discovery system."""
    logger.debug(f'Registering service: {service_info.name}')
    logger.debug(f'Instances: {[inst.host for inst in service_info.instances]}')
    try:
        service = await discovery_service.process(service_info)
        return DiscoveryResponse(
            success=True,
            message=f'Service {service.name} registered successfully',
        )
    except DiscoveryServiceException as e:
        logger.exception(f'Discovery service error: {e}')
        return DiscoveryResponse(
            success=False,
            message=str(e),
        )


@router.delete('/unregister/{service_name}')
async def remove_service(
    service_name: str,
    discovery_service: Annotated[DiscoveryService, Depends(get_discovery_service)],
) -> DiscoveryResponse:
    """Unregister a specific service instance or the entire service."""

    await discovery_service.remove_service(service_name)
    return DiscoveryResponse(
        success=True,
        message=f'Service {service_name} unregistered successfully',
    )


@router.delete('/unregister/{service_name}/{instance_id}')
async def remove_instance(
    service_name: str,
    instance_id: str,
    discovery_service: Annotated[DiscoveryService, Depends(get_discovery_service)],
) -> DiscoveryResponse:
    """Unregister a specific service instance or the entire service."""
    await discovery_service.remove_service_instance(service_name, instance_id)
    return DiscoveryResponse(
        success=True,
        message=f'{instance_id} of service {service_name} unregistered successfully',
    )


@router.get('/services', response_model_by_alias=False)
async def get_services(
    discovery_service: Annotated[DiscoveryService, Depends(get_discovery_service)],
) -> list[ServiceSchema]:
    return await discovery_service.get_all_services()


@router.get('/services/{service_name}', response_model_by_alias=False)
async def get_service_by_name(
    service_name: str,
    discovery_service: Annotated[DiscoveryService, Depends(get_discovery_service)],
) -> ServiceSchema:
    service = await discovery_service.get_service_by_name(service_name)
    return service


@router.post('/services/{service_name}/toggle')
async def enable_disable_service(
    service_name: str,
    discovery_service: Annotated[DiscoveryService, Depends(get_discovery_service)],
    enabled: bool = Body(..., embed=True),
) -> ServiceSchema:
    service = await discovery_service.toggle_service(service_name, enabled)
    return service


@router.patch('/services/{service_name}/change-strategy')
async def change_balancing_strategy(
    service_name: str,
    discovery_service: Annotated[DiscoveryService, Depends(get_discovery_service)],
    strategy: Annotated[ProxyBalancingStrategy, Body(embed=True)],
) -> ServiceSchema:
    service = await discovery_service.change_balancing_strategy(service_name, strategy)
    return service
