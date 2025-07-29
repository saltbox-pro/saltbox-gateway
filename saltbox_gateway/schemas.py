from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
)

from saltbox_sdk.db.schemas_base import User
from saltbox_sdk.discovery_client.schemas import ServiceFrontendConfig


class AccessModel(BaseModel):
    roles: list[str] = Field(default=[])


ANONYMOUS_USER = User(
    sub='anonymous',
    resource_access=None,
    email_verified=False,
    name='Anonymous',
    email='anonymous@localhost',
)


class KeycloakConfig(BaseModel):
    authority: str
    client_id: str
    redirect_uri: str
    client_secret: str | None = None


class DiscoveryServiceConfig(BaseModel):
    auth_config: KeycloakConfig
    services: list[ServiceFrontendConfig]


class ProxyRequestData(BaseModel):
    method: str
    path: str
    query_params: dict[str, Any]
    headers: dict[str, Any]
    body: dict | None = None
    raw_body: bytes | None = None
    user: User

    model_config = ConfigDict(
        extra='forbid',
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cache_key(self) -> str:
        return f'{self.user.sub}:{self.method}:{self.path}:{self.query_params}'

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_cachable(self) -> bool:
        return self.method in ['GET', 'HEAD'] and self.user.sub != ANONYMOUS_USER.sub
