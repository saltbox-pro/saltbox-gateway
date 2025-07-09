from pydantic import (
    BaseModel,
    Field,
    computed_field,
)

from saltbox_gateway.config import SETTINGS
from saltbox_sdk.discovery_client.schemas import ServiceFrontendConfig


class AccessModel(BaseModel):
    roles: list[str] = Field(default=[])


class User(BaseModel):
    sub: str  # = Field(serialization_alias='id')
    resource_access: dict[str, AccessModel] | None = Field(default=None, exclude=True)
    email_verified: bool
    name: str
    email: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def roles(self) -> list[str]:
        client_roles: list[str] = []
        if self.resource_access:
            try:
                client_roles = self.resource_access[SETTINGS.keycloak_client].roles
            except KeyError:
                pass

        return client_roles


class KeycloakConfig(BaseModel):
    authority: str
    client_id: str
    redirect_uri: str
    client_secret: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def keycloak_oidc_url(self) -> str:
        return f'{self.authority}/.well-known/openid-configuration'

    @computed_field  # type: ignore[prop-decorator]
    @property
    def keycloak_authorization_endpoint(self) -> str:
        return f'{self.authority}/protocol/openid-connect/auth'


class DiscoveryServiceConfig(BaseModel):
    auth_config: KeycloakConfig
    services: list[ServiceFrontendConfig]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def keycloak_url(self) -> str:
        return SETTINGS.keycloak_front_url.rstrip('/')
