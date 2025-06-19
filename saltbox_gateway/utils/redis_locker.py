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
        logger.debug(f'Attempting to acquire lock: {self._key} with value: {self._value}')
        while attempts < self._max_attempts:
            logger.debug(f'Attempt №{attempts + 1} to acquire lock: {self._key}')
            if await self._redis.set(self._key, self._value, ex=self._ttl, nx=True):
                logger.debug('Lock acquired...')
                return True
            await asyncio.sleep(0.1)
            attempts += 1
        logger.debug(f'Failed to acquire lock after {self._max_attempts} attempts')
        return False

    async def release(self) -> None:
        """Releasing a lock"""
        logger.debug(f'Releasing lock: {self._key} with value: {self._value}')
        # Use Lua script to ensure atomicity
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        result = await self._redis.eval(script, 1, self._key, self._value)  # type: ignore[no-untyped-call]
        if result:
            logger.debug('Lock released successfully')
        else:
            logger.warning('Lock release failed or lock was not held by this instance')

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
        else:
            logger.debug(f'Lock used successfully: {self._key}')


class AsyncRedisLockerFactory:
    """Factory for creating RedisLocker instances"""

    def __init__(self, redis_client: Redis, ttl: int = 10, max_attempts: int = 10) -> None:
        self._redis = redis_client
        self._ttl = ttl
        self._max_attempts = max_attempts

    def create(self, key: str) -> AsyncRedisLocker:
        """Create a new RedisLocker instance"""
        return AsyncRedisLocker(self._redis, key, self._ttl, self._max_attempts)
