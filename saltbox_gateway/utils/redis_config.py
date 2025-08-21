from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from redis.asyncio import ConnectionPool, Redis

from saltbox_sdk.config.logger_config import logger
from saltbox_sdk.config.redis_config import REDIS_SETTINGS


def _make_pool() -> ConnectionPool:
    return ConnectionPool.from_url(REDIS_SETTINGS.redis_url, **REDIS_SETTINGS.redis_connection_kwargs)


async def close_redis_pool() -> None:
    """Close the Redis connection pool."""
    if POOL:
        await POOL.disconnect(inuse_connections=True)
        logger.debug('Redis connection pool closed.')


POOL = _make_pool()


def get_redis_connection() -> Redis:
    return Redis(connection_pool=POOL)


async def get_redis() -> AsyncGenerator[Redis, None]:
    redis = get_redis_connection()
    yield redis


RedisDependency = Annotated[Redis, Depends(get_redis)]
