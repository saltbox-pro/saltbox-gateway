from typing import Annotated

from fastapi import APIRouter, Depends, Response

from saltbox_gateway.services.proxy import ProxyService, get_proxy_service

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

    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.headers.get('content-type'),
    )
