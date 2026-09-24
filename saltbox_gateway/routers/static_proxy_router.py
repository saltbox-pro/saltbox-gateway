from typing import Annotated

from fastapi import APIRouter, Depends, Response

from saltbox_gateway.services.proxy import ProxyService, build_client_response, get_proxy_service

router = APIRouter(prefix='/static', tags=['Static Proxy'])


@router.api_route('/{service_name}/{path:path}', methods=['GET', 'OPTIONS'])
async def proxy_request(
    service_name: str,
    path: str,
    proxy_service: Annotated[ProxyService, Depends(get_proxy_service)],
) -> Response:
    response = await proxy_service.proxy_static_file(
        service_name=service_name,
        path=path,
    )

    return build_client_response(response)
