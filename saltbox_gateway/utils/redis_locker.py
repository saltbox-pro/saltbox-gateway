import asyncio
import uuid
from types import TracebackType

from redis.asyncio import Redis

from saltbox_gateway.config import logger


class AsyncRedisLocker:
    """Class for managing repository synchronization locks"""

    def __init__(self, redis_client: Redis, key: str, ttl: int = 60, max_attempts: int = 10) -> None:
        self._redis = redis_client
        self._ttl = ttl
        self._key = f'lock:{key}'
        self._value = str(uuid.uuid4())
        self._max_attempts = max_attempts

    async def acquire(self) -> bool:
        """Acquiring a lock"""
        attempts = 0
        while attempts < self._max_attempts:
            if await self._redis.set(self._key, self._value, ex=self._ttl, nx=True):
                logger.debug(f'Lock acquired with attempt #{attempts + 1}: {self._key} ({self._value})')
                return True
            await asyncio.sleep(0.1)
            attempts += 1
        logger.warning(f'Failed to acquire lock after {self._max_attempts} attempts')
        return False

    async def release(self) -> None:
        """Releasing a lock"""
        # Use Lua script to ensure atomicity
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        released = await self._redis.eval(script, 1, self._key, self._value)  # type: ignore[no-untyped-call]
        if released:
            logger.debug(f'Lock released for: {self._key} ({self._value})')
        else:
            logger.warning(f'Lock release failed or lock not held: {self._key}')

    async def __aenter__(self) -> 'AsyncRedisLocker':
        """Context manager enter method"""
        if await self.acquire():
            return self
        else:
            msg = f'Could not acquire lock: {self._key} after {self._max_attempts} attempts'
            logger.exception(msg)
            raise TimeoutError(msg)

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType
    ) -> None:
        """Context manager exit method"""
        await self.release()
        if exc_type:
            logger.error(f'Exception occurred while using lock: {self._key}: {exc_value}')


class AsyncRedisLockerFactory:
    """Factory for creating RedisLocker instances"""

    def __init__(self, redis_client: Redis, ttl: int = 10, max_attempts: int = 10) -> None:
        self._redis = redis_client
        self._ttl = ttl
        self._max_attempts = max_attempts

    def create(self, key: str) -> AsyncRedisLocker:
        """Create a new RedisLocker instance"""
        return AsyncRedisLocker(self._redis, key, self._ttl, self._max_attempts)
