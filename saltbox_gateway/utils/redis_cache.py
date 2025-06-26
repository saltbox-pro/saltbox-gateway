import json
from abc import ABC, abstractmethod
from typing import Any

from redis.asyncio import Redis

from saltbox_gateway.config import logger


class BaseCache(ABC):
    """Base cache class for custom cache implementations."""

    @abstractmethod
    async def get(self, key: str) -> Any:
        """Get a value from the cache by key."""
        raise NotImplementedError

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set a value in the cache with an optional TTL."""
        raise NotImplementedError


class CustomRedisCache(BaseCache):
    """Custom Redis cache class."""

    def __init__(self, redis_client: Redis, namespace: str, ttl: int = 3600) -> None:
        self._redis_client = redis_client
        self._namespace = namespace
        self._ttl = ttl

    async def _format_key(self, key: str) -> str:
        """Format the key with the namespace."""
        return f'cache:{self._namespace}:{key}'

    async def get(self, key: str) -> Any:
        key = await self._format_key(key)
        return await self._redis_client.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        key = await self._format_key(key)
        ttl = ttl or self._ttl
        if isinstance(value, dict):
            value = json.dumps(value)
        await self._redis_client.setex(key, ttl, value)

    @classmethod
    async def clear_cache(cls, redis: Redis, namespace: str | None = None) -> None:
        """Clear the cache for the given namespace or all namespaces."""
        if namespace:
            keys = await redis.keys(f'cache:{namespace}:*')
        else:
            keys = await redis.keys('cache:*')
        if keys:
            await redis.delete(*keys)
            logger.debug('Cache cleared for `%s` namespace', namespace or 'all')
