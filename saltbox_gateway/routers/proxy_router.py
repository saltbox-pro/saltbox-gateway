from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Response

from saltbox_gateway.config import logger
from saltbox_gateway.services.proxy import ProxyService, build_client_response, get_proxy_service
from saltbox_gateway.utils.opa_client import AsyncOpaClient, get_opa_client
from saltbox_sdk.discovery_client.schemas import OPAQueryFilterFormat

router = APIRouter(prefix='/api', tags=['API Proxy'])


@router.api_route('/{service_name}/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
async def proxy_request(
    service_name: str,
    path: str,
    proxy_service: Annotated[ProxyService, Depends(get_proxy_service)],
) -> Response:
    response = await proxy_service.api_proxy(
        service_name=service_name,
        path=path,
    )

    return build_client_response(response)


# Api route for devs
@router.post('/query-translator')
async def query_translator(
    opa_client: Annotated[AsyncOpaClient, Depends(get_opa_client)],
    result: Annotated[dict, Body(embed=True)],
    format: Annotated[
        OPAQueryFilterFormat, Query(..., description='Format to translate queries to')
    ] = OPAQueryFilterFormat.MONGO,
) -> dict:
    logger.debug('result: %s', result)
    return await opa_client.query_translator(result, format=format)


# @router.websocket('/ws/{user_id}')
# async def websocket_proxy(
#     user_id: str,
#     secure_websocket: Annotated[Depends, Depends(get_proxy_service)],
# ) -> None:
#     """
#     WebSocket proxy endpoint.
#     This endpoint allows WebSocket connections to be proxied to the appropriate service.
#     """
#     pass
