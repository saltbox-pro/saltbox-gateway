from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    computed_field,
)

from saltbox_sdk.db.schemas_base import ANONYMOUS_USER, User
from saltbox_sdk.discovery_client.schemas import ServiceFrontendConfig


class KeycloakConfig(BaseModel):
    authority: str
    client_id: str
    redirect_uri: str
    client_secret: str | None = None


class DiscoveryServiceConfig(BaseModel):
    auth_config: KeycloakConfig
    services: list[ServiceFrontendConfig]


class ProxyRequestData(BaseModel):
    method: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    path: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    query_params: dict[str, Any]
    headers: dict[str, str]
    body: Any = None  # any JSON-valid object
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
