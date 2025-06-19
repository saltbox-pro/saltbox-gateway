from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException

from saltbox_gateway.config import logger
from saltbox_gateway.dao.service_dao import ServiceDAOError, ServiceNotFoundError
from saltbox_gateway.schemas import ServiceInstance, ServiceSchema
from saltbox_gateway.services.discovery import DiscoveryService, DiscoveryServiceError, get_discovery_service

router = APIRouter(prefix='/discovery', tags=['Discovery'])


@router.post('/register')
async def register_service(
    service_info: ServiceSchema,
    discovery_service: Annotated[DiscoveryService, Depends(get_discovery_service)],
) -> dict:
    """Register a new service in the discovery system."""

    try:
        service = await discovery_service.process(service_info)
        msg = f'Service {service.service_name} registered successfully'
    except DiscoveryServiceError as e:
        logger.exception(f'Discovery service error: {e}')
        service = None
        msg = str(e)

    return {
        'status': 'success' if service else 'error',
        'message': msg,
        'service': service if service else None,
    }


@router.post('/unregister/{service_name}')
async def remove_service_or_instance(
    service_name: str,
    discovery_service: Annotated[DiscoveryService, Depends(get_discovery_service)],
    instance: Annotated[ServiceInstance | None, Body(embed=True)] = None,
) -> dict:
    """Unregister a specific service instance."""
    if instance:
        logger.debug(f'Unregistering service instance {service_name} at {instance.host}:{instance.port}')

        try:
            await discovery_service.remove_service_instance(service_name, instance.host, instance.port)
            success = True
            msg = f'Service instance {instance.host}:{instance.port} unregistered successfully'
        except ServiceNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ServiceDAOError as e:
            logger.exception(f'Error unregistering service instance {service_name}: {e}')
            raise HTTPException(status_code=500, detail='Internal server error') from e
    else:
        logger.debug(f'Unregistering all instances of service {service_name}')
        try:
            await discovery_service.remove_service(service_name)
            success = True
            msg = f'Service {service_name} unregistered successfully'
        except ServiceNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ServiceDAOError as e:
            logger.exception(f'Error unregistering service {service_name}: {e}')
            raise HTTPException(status_code=500, detail='Internal server error') from e

    return {
        'status': 'success' if success else 'error',
        'message': msg,
    }


@router.get('/services')
async def get_services(
    discovery_service: Annotated[DiscoveryService, Depends(get_discovery_service)],
) -> list[ServiceSchema]:
    return await discovery_service.get_all_services()


@router.post('/services/{service_name}/toggle')
async def enable_disable_service(
    service_name: str,
    discovery_service: Annotated[DiscoveryService, Depends(get_discovery_service)],
    enabled: bool = Body(..., embed=True),
) -> ServiceSchema:
    logger.debug(f'{enabled}')
    try:
        service = await discovery_service.toggle_service(service_name, enabled)
        return service
    except ServiceNotFoundError:
        raise HTTPException(status_code=404, detail=f'Service {service_name} not found') from None
