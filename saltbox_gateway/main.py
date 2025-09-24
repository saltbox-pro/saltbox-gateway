import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from saltbox_gateway import __version__
from saltbox_gateway.config import APP_DESC, APP_NAME, SETTINGS, logger
from saltbox_gateway.middlwares.authn import AuthMiddleware
from saltbox_gateway.middlwares.request_id import RequestIDMiddleware
from saltbox_gateway.routers.discovery_router import router as discovery_router
from saltbox_gateway.routers.permissions_router import router as permissions_router
from saltbox_gateway.routers.proxy_router import router as proxy_router
from saltbox_gateway.routers.static_proxy_router import router as static_proxy_router
from saltbox_gateway.services.health_checker import get_health_checker_service
from saltbox_gateway.tmp_ws_proxy.router import ws_core_jobs_router, ws_core_tasks_router
from saltbox_gateway.utils.redis_cache import CustomRedisCache
from saltbox_gateway.utils.redis_config import close_redis_pool, get_redis_connection
from saltbox_sdk.exceptions import SaltBoxBaseException
from saltbox_sdk.fastapi_utils.custom_openapi import custom_openapi, patch_swagger_config
from saltbox_sdk.fastapi_utils.exception_handlers import custom_http_handler
from saltbox_sdk.fastapi_utils.promethes_metrics.exporter import PrometheusExporter


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator:
    health_checker = get_health_checker_service()
    health_task = None
    if health_checker:
        logger.debug('Starting health checker service')
        health_task = asyncio.create_task(health_checker.start())
    else:
        logger.warning('Health checker service is not available')
    yield

    if health_task:
        await health_checker.stop()
        health_task.cancel()
        try:
            await health_task
        except asyncio.CancelledError:
            pass
    # Clean up redis cache
    await CustomRedisCache.clear_cache(get_redis_connection())
    # Close the Redis connection pool
    await close_redis_pool()


app_config: dict[str, Any] = {
    'title': APP_NAME,
    'lifespan': lifespan,
    'version': __version__,
    'description': APP_DESC,
    'docs_url': '/api/discovery/docs',
    'openapi_url': '/api/discovery/openapi.json',
    'swagger_ui_oauth2_redirect_url': '/api/discovery/docs/oauth2-redirect',
}

app_config = patch_swagger_config(app_config)

app = FastAPI(**app_config)

app.add_middleware(RequestIDMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=SETTINGS.origins,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.add_middleware(
    AuthMiddleware,
    # Need add SETTINGS.base_url_root_path.rstrip('/') + uri in some cases
    excluded_paths=[uri for uri in [app.docs_url, app.openapi_url, app.swagger_ui_oauth2_redirect_url] if uri]
    + [rf'/api/{module}/(docs|openapi\.json|docs/oauth2-redirect)$' for module in SETTINGS.official_modules]
    + [r'/static/(.*)']
    + [r'/metrics']
    + [r'/api/discovery(?:/.*)?$']
    + [r'/api/core/system/[\w-]+/authorized_keys'],
)
PrometheusExporter(app).expose_metrics()
app.add_exception_handler(SaltBoxBaseException, custom_http_handler)


app.include_router(permissions_router)
app.include_router(discovery_router)
app.include_router(proxy_router, include_in_schema=False)
app.include_router(static_proxy_router, include_in_schema=False)
app.include_router(ws_core_jobs_router, include_in_schema=False)
app.include_router(ws_core_tasks_router, include_in_schema=False)


app.openapi = partial(custom_openapi, app, app_config)  # type: ignore[method-assign]
