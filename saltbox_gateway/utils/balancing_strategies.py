import secrets
from abc import ABC, abstractmethod
from collections.abc import Callable

from redis.asyncio import Redis

from saltbox_sdk.discovery_client.schemas import ProxyBalancingStrategy, ServiceInstance


class BalancingStrategy(ABC):
    @abstractmethod
    async def choose(self, service_name: str, instances: list[ServiceInstance]) -> ServiceInstance:
        """Choose an instance from the list of instances."""
        pass


class RandomBalancingStrategy(BalancingStrategy):
    async def choose(self, service_name: str, instances: list[ServiceInstance]) -> ServiceInstance:
        """Randomly choose an instance from the list of instances."""
        rand_elem = secrets.randbelow(len(instances))
        return instances[rand_elem]


class RoundRobinBalancingStrategy(BalancingStrategy):
    def __init__(self, redis_client: Redis):
        self.redis_client = redis_client

    async def choose(self, service_name: str, instances: list[ServiceInstance]) -> ServiceInstance:
        key = f'balance:rr:{service_name}'
        idx = await self.redis_client.incr(key)
        return instances[(idx - 1) % len(instances)]


class WeightedRoundRobinBalancingStrategy(BalancingStrategy):
    def __init__(self, redis_client: Redis):
        self.redis_client = redis_client

    async def choose(self, service_name: str, instances: list[ServiceInstance]) -> ServiceInstance:
        weighted_list = []
        for idx, inst in enumerate(instances):
            weight = getattr(inst, 'weight', 1)
            weighted_list.extend([idx] * weight)

        key = f'balance:wrr:{service_name}'
        pos = await self.redis_client.incr(key)
        idx = weighted_list[(pos - 1) % len(weighted_list)]
        return instances[idx]


def balancing_strategy_factory(redis_client: Redis) -> Callable[[str], BalancingStrategy]:
    def factory(strategy_name: str) -> BalancingStrategy:
        if strategy_name == ProxyBalancingStrategy.RANDOM:
            return RandomBalancingStrategy()
        elif strategy_name == ProxyBalancingStrategy.ROUND_ROBIN:
            return RoundRobinBalancingStrategy(redis_client)
        elif strategy_name == ProxyBalancingStrategy.WEIGHTED_ROUND_ROBIN:
            return WeightedRoundRobinBalancingStrategy(redis_client)
        else:
            return RandomBalancingStrategy()

    return factory
