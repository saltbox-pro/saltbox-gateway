import json
import time
from typing import Annotated

from fastapi.params import Depends
from redis.asyncio import Redis

from saltbox_gateway.exceptions import (
    ServiceAlreadyExistsException,
    ServiceCreationException,
    ServiceDAOException,
    ServiceNameRequiredException,
    ServiceNotFoundException,
)
from saltbox_gateway.utils.redis_config import get_redis


class FrontDAO:
    def __init__(self, redis_client: Redis) -> None:
        self.redis_client = redis_client
        self._key_prefix = 'discovery_front'

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

    async def list(self) -> list[dict]:
        keys = await self.redis_client.keys(f'{self._key_prefix}:*')
        services = []
        for key in keys:
            service_data = await self.redis_client.hgetall(key)
            if service_data:
                clean_data = self._decode_redis_hash(service_data).get('data', {})
                services.append(clean_data)
        return services

    async def create(self, service_data: dict) -> dict:
        created_service = await self._save(service_data, must_exist=False)

        if not created_service:
            raise ServiceCreationException(service_data.get('name', 'Unknown service'))
        return created_service

    async def _save(self, service_data: dict, must_exist: bool) -> dict | None:
        service_name = service_data.get('service_name')
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
        saved_service = await self.redis_client.hgetall(service_key)

        if not saved_service:
            return None

        return self._decode_redis_hash(saved_service)


def get_front_dao(redis: Annotated[Redis, Depends(get_redis)]) -> FrontDAO:
    """Dependency to get the FrontDAO instance."""
    return FrontDAO(redis)
