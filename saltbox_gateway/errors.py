from fastapi import WebSocketException, status

from saltbox_sdk.fastapi_utils.errors import SaltBoxBaseError


class GatewayError(SaltBoxBaseError):
    """Base class for all gateway-related exceptions."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail: str = 'An unexpected error occurred in the gateway service.'

    def __str__(self) -> str:
        return f'{self.__class__.__name__}: {self.detail}'


# DAO Errors
class ServiceDAOError(GatewayError):
    """Base exception for ServiceDAO errors."""

    detail: str = 'An error occurred while accessing the service data store.'


class ServiceNotFoundError(ServiceDAOError):
    """Exception raised when a service is not found."""

    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.detail = f'Service "{service_name}" not found.'
        super().__init__(self.detail)


class ServiceAlreadyExistsError(ServiceDAOError):
    """Exception raised when a service already exists."""

    status_code = status.HTTP_409_CONFLICT

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.detail = f'Service "{service_name}" already exists.'
        super().__init__(self.detail)


class ServiceNameIsRequiredError(ServiceDAOError):
    """Exception raised when a service name is required but not provided."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self) -> None:
        self.detail = 'Service name is required.'
        super().__init__(self.detail)


class ServiceCreationError(ServiceDAOError):
    """Exception raised when there is an error creating a service."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.detail = f'Error creating service "{service_name}".'
        super().__init__(self.detail)


class ServiceUpdateError(ServiceDAOError):
    """Exception raised when there is an error updating a service."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.detail = f'Error updating service "{service_name}".'
        super().__init__(self.detail)


class ServiceDeletionError(ServiceDAOError):
    """Exception raised when there is an error deleting a service."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.detail = f'Error deleting service "{service_name}".'
        super().__init__(self.detail)


# Discovery Errors
class DiscoveryServiceError(GatewayError):
    """Base exception for DiscoveryService errors."""

    detail: str = 'An error occurred in the discovery service.'


class ServiceIsNotOfficial(DiscoveryServiceError):
    """Exception raised when a service is not an official module."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.detail = f'Service "{service_name}" is not an official module.'
        super().__init__(self.detail)


class ServiceInstanceNotFoundError(DiscoveryServiceError):
    """Exception raised when a service instance is not found."""

    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, service_name: str, instance_id: str) -> None:
        self.service_name = service_name
        self.instance_id = instance_id
        self.detail = f'Service instance "{instance_id}" not found in service "{service_name}".'
        super().__init__(self.detail)


# Proxy Errors
class ProxyServiceError(GatewayError):
    """Base exception for ProxyService errors."""

    detail: str = 'An error occurred while proxying the request.'


class ServiceDisabledError(ProxyServiceError):
    """Exception raised when a service is disabled."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.detail = f'Service "{service_name}" is currently disabled.'
        super().__init__(self.detail)


class ApiProxyRequestError(ProxyServiceError):
    """Exception raised when there is an error processing the API proxy request."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, status_code: int | None = None, message: str | None = None) -> None:
        self.detail = 'An error occurred while processing the API proxy request.'
        if status_code:
            self.status_code = status_code
        if message:
            self.detail += f' Details: {message}'
        super().__init__(self.detail)


class ServiceHasNoInstancesError(ProxyServiceError):
    """Exception raised when a service has no instances available."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.detail = f'Service "{service_name}" has no instances available.'
        super().__init__(self.detail)


class ServiceHasNoHealthyInstancesError(ProxyServiceError):
    """Exception raised when no healthy instance is found for a service."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.detail = f'No healthy instance found for service "{service_name}".'
        super().__init__(self.detail)


class NotEnoughPermissionsError(ProxyServiceError):
    """Exception raised when the user does not have enough permissions to access a service."""

    status_code = status.HTTP_403_FORBIDDEN

    def __init__(self, service_name: str, path: str | None = None) -> None:
        self.service_name = service_name
        self.path = path
        if path:
            self.detail = f'You do not have enough permissions to access "{path}" of service "{service_name}".'
        else:
            self.detail = f'You do not have enough permissions to access service "{service_name}".'
        super().__init__(self.detail)


class ProxyStaticFileError(ProxyServiceError):
    """Exception raised when there is an error proxying a static file."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message: str | None = None) -> None:
        self.detail = 'An error occurred while proxying the static file.'
        if message:
            self.detail = self.detail + f' Details: {message}'
        super().__init__(self.detail)


class ServiceHasNoEndpointsError(ProxyServiceError):
    """Exception raised when a service has no endpoints defined."""

    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.detail = f'Service "{service_name}" has no endpoints defined.'
        super().__init__(self.detail)


class ServiceEndpointNotFoundError(ProxyServiceError):
    """Exception raised when a service endpoint is not found."""

    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, service_name: str, endpoint: str) -> None:
        self.service_name = service_name
        self.endpoint = endpoint
        self.detail = f'Endpoint "{endpoint}" not found in service "{service_name}".'
        super().__init__(self.detail)


class ProxyOpaClientInitializationError(ProxyServiceError):
    """Exception raised when there is an error initializing the OPA client."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message: str | None = None) -> None:
        self.detail = 'An error occurred while initializing the OPA client.'
        if message:
            self.detail = self.detail + f' Details: {message}'
        super().__init__(self.detail)


# OPA Client Errors
class AsyncOpaClientError(GatewayError):
    """Base exception for OPA client errors."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail: str = 'An error occurred while communicating with the OPA server.'

    def __init__(self, message: str | None = None) -> None:
        if message:
            self.detail = f'{self.detail} Details: {message}'
        super().__init__(self.detail)


class OpaRequestError(AsyncOpaClientError):
    """Exception raised when there is an error making a request to the OPA server."""

    detail: str = 'An error occurred while making a request to the OPA server.'


class OpaResponseFormatError(AsyncOpaClientError):
    """Exception raised when the OPA server response format is invalid."""

    detail: str = 'Invalid OPA response format.'


# Keycloak OIDC Errors
class KeycloakOIDCError(GatewayError):
    """Base class for Keycloak OIDC errors."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail: str = 'An error occurred while processing Keycloak OIDC operations.'


class AuthorizationUrlError(KeycloakOIDCError):
    """Exception raised when the Keycloak OIDC authorization endpoint is not configured."""

    status_code = status.HTTP_401_UNAUTHORIZED

    def __init__(self) -> None:
        self.detail = 'Authorization URL not found in OIDC config. Please check your Keycloak OIDC settings.'
        super().__init__(self.detail)


class TokenUrlError(KeycloakOIDCError):
    """Exception raised when the Keycloak OIDC token endpoint is not configured."""

    status_code = status.HTTP_401_UNAUTHORIZED

    def __init__(self) -> None:
        self.detail = 'Token URL not found in OIDC config. Please check your Keycloak OIDC settings.'
        super().__init__(self.detail)


class IssuerError(KeycloakOIDCError):
    """Exception raised when the Keycloak OIDC issuer is not configured."""

    status_code = status.HTTP_401_UNAUTHORIZED

    def __init__(self) -> None:
        self.detail = 'Issuer not found in OIDC config. Please check your Keycloak OIDC settings.'
        super().__init__(self.detail)


class OIDCConfigFetchError(KeycloakOIDCError):
    """Exception raised when there is an error fetching the OIDC config."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self) -> None:
        self.detail = 'Error fetching OIDC config. Keycloak server is unavailable.'
        super().__init__(self.detail)


class OIDCConfigTimeoutError(KeycloakOIDCError):
    """Exception raised when there is a timeout fetching the OIDC config."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self) -> None:
        self.detail = 'Timeout error fetching OIDC config. Keycloak server is unavailable.'
        super().__init__(self.detail)


class OIDCConfigUnexpectedError(KeycloakOIDCError):
    """Exception raised for unexpected errors fetching the OIDC config."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self) -> None:
        self.detail = 'Unexpected error fetching OIDC config'
        super().__init__(self.detail)


class JWKSKeyNotFoundError(KeycloakOIDCError):
    """Exception raised when a key is not found in JWKS."""

    status_code = status.HTTP_401_UNAUTHORIZED

    def __init__(self) -> None:
        self.detail = 'Key not found in JWKS.'
        super().__init__(self.detail)


class JWKSUriNotFoundError(KeycloakOIDCError):
    """Exception raised when JWKS URI is not found in OIDC config."""

    status_code = status.HTTP_401_UNAUTHORIZED

    def __init__(self) -> None:
        self.detail = 'JWKS URI not found in OIDC config.'
        super().__init__(self.detail)


class JWKSFetchError(KeycloakOIDCError):
    """Exception raised when there is an error fetching JWKS."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self) -> None:
        self.detail = 'Error fetching JWKS. Keycloak server is unavailable.'
        super().__init__(self.detail)


class JWKSFetchTimeoutError(KeycloakOIDCError):
    """Exception raised when there is a timeout fetching JWKS."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self) -> None:
        self.detail = 'Timeout error fetching JWKS. Keycloak server is unavailable.'
        super().__init__(self.detail)


class AuthorizationHeaderInvalidError(KeycloakOIDCError):
    """Exception raised when the authorization header is missing or invalid."""

    status_code = status.HTTP_401_UNAUTHORIZED

    def __init__(self) -> None:
        self.detail = 'Authorization header is missing or invalid.'
        super().__init__(self.detail)


class JWTDecodeHeaderError(KeycloakOIDCError):
    """Exception raised when there is a decode error for JWT token header."""

    status_code = status.HTTP_401_UNAUTHORIZED

    def __init__(self) -> None:
        self.detail = 'Decode error for JWT token header.'
        super().__init__(self.detail)


class JWTKidNotFoundError(KeycloakOIDCError):
    """Exception raised when KID is not found in token."""

    status_code = status.HTTP_401_UNAUTHORIZED

    def __init__(self) -> None:
        self.detail = 'KID not found in token.'
        super().__init__(self.detail)


class JWTExpiredError(KeycloakOIDCError):
    """Exception raised when the token has expired."""

    status_code = status.HTTP_401_UNAUTHORIZED

    def __init__(self) -> None:
        self.detail = 'Token has expired'
        super().__init__(self.detail)


class JWTInvalidTokenError(KeycloakOIDCError):
    """Exception raised when the token is invalid."""

    status_code = status.HTTP_401_UNAUTHORIZED

    def __init__(self, message: str = 'Invalid token') -> None:
        self.detail = message
        super().__init__(self.detail)


class JWTValidationError(KeycloakOIDCError):
    """Exception raised when there is a token validation error."""

    status_code = status.HTTP_401_UNAUTHORIZED

    def __init__(self) -> None:
        self.detail = 'Token validation error'
        super().__init__(self.detail)


# WebSocket Errors
class SecureWebSocketError(WebSocketException):
    """Base class for secure WebSocket errors."""

    status_code = status.WS_1011_INTERNAL_ERROR
    detail: str = 'An unexpected error occurred in the secure WebSocket connection.'

    def __init__(self, message: str | None = None) -> None:
        if message:
            self.detail = f'{self.detail} Details: {message}'
        super().__init__(code=self.status_code, reason=self.detail)


class SecureWebSocketPolicyViolation(SecureWebSocketError):
    """Generic error means message violates policy of socket"""

    status_code = status.WS_1008_POLICY_VIOLATION
    detail: str = 'WebSocket policy violation occurred.'


class SecureWebSocketServerError(SecureWebSocketError):
    """Unexpected conditions prevents from fulfilling a request"""

    status_code = status.WS_1011_INTERNAL_ERROR
    detail: str = 'Internal server error in secure WebSocket connection.'
