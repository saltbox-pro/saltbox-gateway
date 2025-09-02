from typing import Annotated

from fastapi import APIRouter, Depends

from saltbox_gateway.services.proxy import ProxyService, get_proxy_service

router = APIRouter(prefix='/api/permissions', tags=['Permissions'])


@router.get('/{service_name}', operation_id='check_service_permissions')
async def check_service_permissions(
    service_name: str,
    proxy_service: Annotated[ProxyService, Depends(get_proxy_service)],
) -> dict:
    """
    Check if the user has permission to perform a specific action.
    """
    service_name = service_name.strip('/').lower()
    service_paths = {
        'core': [
            'collections',
            'masters',
            'jobs',
            'settings/sls-repos',
            'json-schemas',
            'tasks/template',
        ],
        'scheduler': [
            'tasks',
            'task-templates',
        ],
    }
    return await proxy_service.check_resources_permissions(
        service_name=service_name, paths=service_paths.get(service_name, [])
    )
