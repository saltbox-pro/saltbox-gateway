import json
from typing import Annotated, cast

from fastapi import Depends
from redis.asyncio import Redis

from saltbox_gateway.exceptions import UserSettingsDAOException
from saltbox_gateway.utils.redis_config import get_redis


class UserSettingsDAO:
    def __init__(self, redis_client: Redis) -> None:
        self.redis_client = redis_client
        self._key_prefix = 'user_settings'

    async def get(self, user_sub: str) -> dict:
        service_key = f'{self._key_prefix}:{user_sub}'
        service_data = await self.redis_client.get(service_key)
        if not service_data:
            return {}
        return cast(dict, json.loads(service_data))

    async def create_or_update(self, user_sub: str, settings: dict) -> dict:
        user_key = f'{self._key_prefix}:{user_sub}'

        await self.redis_client.set(user_key, json.dumps(settings))
        stored_settings = await self.redis_client.get(user_key)

        if not stored_settings:
            msg = 'Failed to save user settings.'
            raise UserSettingsDAOException(msg)

        return cast(dict, json.loads(stored_settings))


def get_user_settings_dao(redis: Annotated[Redis, Depends(get_redis)]) -> UserSettingsDAO:
    """Dependency to get the UserSettingsDAO instance."""
    return UserSettingsDAO(redis)
