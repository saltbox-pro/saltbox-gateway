import json
import time
from typing import Annotated

from fastapi.params import Depends
from redis.asyncio import Redis

from saltbox_gateway.config import SETTINGS
from saltbox_gateway.exceptions import (
    ServiceAlreadyExistsException,
    ServiceCreationException,
    ServiceDAOException,
    ServiceDeleteException,
    ServiceNameRequiredException,
    ServiceNotFoundException,
    ServiceUpdateException,
)
from saltbox_gateway.utils.redis_config import get_redis


class ServiceDAO:
    def __init__(self, redis_client: Redis) -> None:
        self.redis_client = redis_client
        self._key_prefix = 'discovery'

    def _decode_redis_hash(self, data: dict) -> dict:
        decoded = {k.decode(): v.decode() for k, v in data.items()}
        if 'data' in decoded:
            try:
                decoded['data'] = json.loads(decoded['data'])
            except Exception as e:
                msg = f'Failed to decode service data: {e}'
                raise ServiceDAOException(msg) from e
        if 'last_updated' in decoded:
            try:
                decoded['last_updated'] = float(decoded['last_updated'])
            except ValueError as e:
                msg = f'Invalid last_updated timestamp: {e}'
                raise ServiceDAOException(msg) from e
        return decoded

    async def get(self, service_name: str) -> dict:
        service_key = f'{self._key_prefix}:{service_name}'
        service_data = await self.redis_client.hgetall(service_key)
        if not service_data:
            raise ServiceNotFoundException(service_name)

        return self._decode_redis_hash(service_data)

    async def get_or_none(self, service_name: str) -> dict | None:
        try:
            return await self.get(service_name)
        except ServiceNotFoundException:
            return None

    async def list(self) -> list[dict]:
        keys = await self.redis_client.keys(f'{self._key_prefix}:*')
        services = []
        for key in keys:
            service_data = await self.redis_client.hgetall(key)
            if service_data:
                services.append(self._decode_redis_hash(service_data))
        return services

    async def create(self, service_data: dict) -> dict:
        created_service = await self._save(service_data, must_exist=False)

        if not created_service:
            raise ServiceCreationException(service_data.get('name', 'Unknown service'))
        return created_service

    async def update(self, service_data: dict) -> dict:
        updated_service = await self._save(service_data, must_exist=True)

        if not updated_service:
            raise ServiceUpdateException(service_data.get('name', 'Unknown service'))
        return updated_service

    async def delete(self, service_name: str) -> None:
        service_key = f'{self._key_prefix}:{service_name}'
        if not await self.redis_client.exists(service_key):
            raise ServiceNotFoundException(service_name)
        result = await self.redis_client.delete(service_key)
        if result == 0:
            raise ServiceDeleteException(service_name)

        return None

    async def _save(self, service_data: dict, must_exist: bool) -> dict | None:
        service_name = service_data.get('name')
        if not service_name:
            raise ServiceNameRequiredException()

        service_key = f'{self._key_prefix}:{service_name}'
        exists = await self.redis_client.exists(service_key)
        if must_exist and not exists:
            raise ServiceNotFoundException(service_name)
        if not must_exist and exists:
            raise ServiceAlreadyExistsException(service_name)

        await self.redis_client.hset(
            service_key, mapping={'data': json.dumps(service_data), 'last_updated': time.time()}
        )
        await self.redis_client.expire(service_key, SETTINGS.app.service_registration_ttl)
        saved_service = await self.redis_client.hgetall(service_key)

        if not saved_service:
            return None

        return self._decode_redis_hash(saved_service)


def get_service_dao(redis: Annotated[Redis, Depends(get_redis)]) -> ServiceDAO:
    """Dependency to get the ServiceDAO instance."""
    return ServiceDAO(redis)
