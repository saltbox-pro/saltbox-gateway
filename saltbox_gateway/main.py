import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from saltbox_gateway import __version__
from saltbox_gateway.config import APP_DESC, APP_NAME, SETTINGS, logger
from saltbox_gateway.errors import GatewayError
from saltbox_gateway.exception_handlers import custom_http_handler
from saltbox_gateway.middlwares.authn import AuthMiddleware
from saltbox_gateway.routers.discovery_router import router as discovery_router
from saltbox_gateway.routers.proxy_router import router as proxy_router
from saltbox_gateway.routers.static_proxy_router import router as static_proxy_router
from saltbox_gateway.services.health_checker import get_health_checker_service
from saltbox_gateway.utils.custom_openapi import get_custom_openapi_schema
from saltbox_gateway.utils.redis_cache import CustomRedisCache
from saltbox_gateway.utils.redis_config import close_redis_pool, get_redis_connection


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
    'redoc_url': None,
    'swagger_ui_init_oauth': {
        'clientId': SETTINGS.keycloak_client,
        'clientSecret': SETTINGS.keycloak_client_secret,
        'scopes': 'openid',
    },
    'swagger_ui_parameters': {
        'displayRequestDuration': True,
        'filter': True,
    },
    # 'root_path': SETTINGS.base_url_root_path,
}

app = FastAPI(**app_config)


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
    + ['/api/core/docs', '/api/core/openapi.json']
    + [r'/api/discovery(?:/.*)?$']
    + [r'/api/core/system/[\w-]+/authorized_keys'],
)

app.add_exception_handler(GatewayError, custom_http_handler)


app.include_router(discovery_router)
app.include_router(proxy_router, include_in_schema=False)
app.include_router(static_proxy_router, include_in_schema=False)


def custom_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema

    logger.debug('Generating custom OpenAPI schema')

    app.openapi_schema = get_custom_openapi_schema(
        app_configs=app_config,
        routes=app.routes,
        # servers=[{'url': SETTINGS.base_url_root_path}],
    )
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[method-assign]
