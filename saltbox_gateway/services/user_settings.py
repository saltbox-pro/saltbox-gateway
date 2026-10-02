from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis

from saltbox_gateway.dao.user_settings_dao import UserSettingsDAO, get_user_settings_dao
from saltbox_gateway.utils.redis_config import get_redis
from saltbox_gateway.utils.redis_locker import AsyncRedisLockerFactory


class UserSettingsService:
    """Service for managing user settings operations."""

    def __init__(self, dao: UserSettingsDAO, locker: AsyncRedisLockerFactory, request: Request) -> None:
        self._dao = dao
        self._locker = locker
        self._user_sub = request.state.user.sub

    async def get(self) -> dict:
        return await self._dao.get(user_sub=self._user_sub)

    async def create_or_update(self, settings: dict) -> dict:
        return await self._dao.create_or_update(user_sub=self._user_sub, settings=settings)


def get_user_settings_service(
    request: Request,
    dao: Annotated[UserSettingsDAO, Depends(get_user_settings_dao)],
    redis_client: Annotated[Redis, Depends(get_redis)],
) -> UserSettingsService:
    locker_factory = AsyncRedisLockerFactory(redis_client=redis_client)
    return UserSettingsService(dao, locker_factory, request=request)
