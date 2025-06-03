from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from saltbox_gateway import __version__
from saltbox_gateway.config import APP_DESC, APP_NAME, SETTINGS, logger


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator:
    logger.debug('Starting Salt.Box Gateway lifespan context manager')
    yield


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


@app.get('/health', openapi_extra={'x-opa-policy': 'health_check'})
async def health_check() -> dict:
    """Health check для API Gateway"""
    try:
        # Check Redis connection
        # await redis_client.redis.ping()
        return {'status': 'healthy', 'service': 'api-gateway'}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f'Unhealthy: {e!s}') from None
