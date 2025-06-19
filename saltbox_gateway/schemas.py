from enum import Enum

from pydantic import BaseModel


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


class ServiceEndpoint(BaseModel):
    path: str
    method: str = 'GET'
    opa_policy: str | None = None


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
