from enum import Enum

from pydantic import BaseModel, Field


class ProxyBalancingStrategy(str, Enum):
    RANDOM = 'rand'
    ROUND_ROBIN = 'rr'
    WEIGHTED_ROUND_ROBIN = 'wrr'


class ServiceType(str, Enum):
    OFFICIAL = 'official'
    THIRD_PARTY = 'third-party'


class ServiceStatus(str, Enum):
    RUNNING = 'running'
    STOPPED = 'stopped'
    ERROR = 'error'


class ServiceInstance(BaseModel):
    host: str
    port: int
    base_route: str | None = None
    version: str | None = None
    healthy: bool | None = None
    last_check: float | None = None
    last_healthy: float | None = None


class OPAQueryFilterFormat(str, Enum):
    MONGO = 'mongo'
    SQL = 'sql'


class OPAConfig(BaseModel):
    policy: str = 'public'
    is_partial: bool = False
    partial_query: str | None = None
    unknowns: list[str] | None = None
    query_filter_format: OPAQueryFilterFormat | None = None


class ServiceEndpoint(BaseModel):
    path: str
    method: str
    summary: str = ''
    description: str = ''
    opa_config: OPAConfig = Field(default_factory=OPAConfig)
    cache_ttl: int = 0


class ServiceSchema(BaseModel):
    service_name: str
    service_type: ServiceType
    display_name: str
    description: str
    vendor: str
    instances: list[ServiceInstance]
    endpoints: list[ServiceEndpoint] = []
    health_check: str = '/health'
    auto_discover_routes: bool = True
    enabled: bool = True
    balancing_strategy: ProxyBalancingStrategy = ProxyBalancingStrategy.RANDOM
