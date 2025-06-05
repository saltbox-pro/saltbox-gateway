from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from saltbox_gateway import __version__
from saltbox_gateway.config import APP_DESC, APP_NAME, SETTINGS, logger
from saltbox_gateway.middlwares.authn import AuthMiddleware
from saltbox_gateway.utils.redis_cache import CustomRedisCache
from saltbox_gateway.utils.redis_config import RedisDependency, close_redis_pool, get_redis_connection


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator:
    logger.debug('Starting Salt.Box Gateway lifespan context manager')
    yield
    logger.debug('Ending Salt.Box Gateway lifespan context manager')
    # Clean up redis cache
    await CustomRedisCache.clear_cache(get_redis_connection())
    # Close the Redis connection pool
    await close_redis_pool()


app = FastAPI(
    title=APP_NAME,
    description=APP_DESC,
    version=__version__,
    lifespan=lifespan,
)


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
    excluded_paths=[uri for uri in [app.docs_url, app.openapi_url, app.swagger_ui_oauth2_redirect_url] if uri],
)


@app.get('/health', openapi_extra={'x-opa-policy': 'health_check'})
async def health_check(redis: RedisDependency) -> dict:
    """Health check для API Gateway"""
    try:
        # Check Redis connection
        pong = await redis.ping()
        return {'status': 'healthy', 'service': 'api-gateway', 'redis': pong}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f'Unhealthy: {e!s}') from None
