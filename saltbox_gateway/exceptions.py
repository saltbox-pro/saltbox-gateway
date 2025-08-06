from fastapi import WebSocketException, status

from saltbox_sdk.exceptions import SaltBoxBaseException


class GatewayException(SaltBoxBaseException):
    """Base class for all gateway-related exceptions."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail: str = 'An unexpected error occurred in the gateway service.'


# DAO Errors
class ServiceDAOException(GatewayException):
    """Base exception for ServiceDAO errors."""

    detail: str = 'An error occurred while accessing the service data store.'


class ServiceNotFoundException(ServiceDAOException):
    """Exception raised when a service is not found."""

    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.detail = f'Service "{service_name}" not found.'
        super().__init__(self.detail)


class ServiceAlreadyExistsException(ServiceDAOException):
    """Exception raised when a service already exists."""

    status_code = status.HTTP_409_CONFLICT

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.detail = f'Service "{service_name}" already exists.'
        super().__init__(self.detail)


class ServiceNameRequiredException(ServiceDAOException):
    """Exception raised when a service name is required but not provided."""

    status_code = status.HTTP_400_BAD_REQUEST
    detail = 'Service name is required.'


class ServiceCreationException(ServiceDAOException):
    """Exception raised when there is an error creating a service."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.detail = f'Error creating service "{service_name}".'
        super().__init__(self.detail)


class ServiceUpdateException(ServiceDAOException):
    """Exception raised when there is an error updating a service."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.detail = f'Error updating service "{service_name}".'
        super().__init__(self.detail)


class ServiceDeleteException(ServiceDAOException):
    """Exception raised when there is an error deleting a service."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.detail = f'Error deleting service "{service_name}".'
        super().__init__(self.detail)


# Discovery Errors
class DiscoveryServiceException(GatewayException):
    """Base exception for DiscoveryService errors."""

    detail: str = 'An error occurred in the discovery service.'


class NonOfficialServiceException(DiscoveryServiceException):
    """Exception raised when a service is not an official module."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.detail = f'Service "{service_name}" is not an official module.'
        super().__init__(self.detail)


class ServiceInstanceNotFoundException(DiscoveryServiceException):
    """Exception raised when a service instance is not found."""

    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, service_name: str, instance_id: str) -> None:
        self.service_name = service_name
        self.instance_id = instance_id
        self.detail = f'Service instance "{instance_id}" not found in service "{service_name}".'
        super().__init__(self.detail)


# Proxy Errors
class ProxyServiceException(GatewayException):
    """Base exception for ProxyService errors."""

    detail: str = 'An error occurred while proxying the request.'


class ServiceDisabledException(ProxyServiceException):
    """Exception raised when a service is disabled."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.detail = f'Service "{service_name}" is currently disabled.'
        super().__init__(self.detail)


class ApiProxyRequestException(ProxyServiceException):
    """Exception raised when there is an error processing the API proxy request."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail = 'An error occurred while processing the API proxy request.'

    def __init__(self, detail: str | None = None, status_code: int | None = None) -> None:
        if status_code:
            self.status_code = status_code
        if detail:
            self.detail = detail
        super().__init__(self.detail)


class ServiceHasNoInstancesException(ProxyServiceException):
    """Exception raised when a service has no instances available."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.detail = f'Service "{service_name}" has no instances available.'
        super().__init__(self.detail)


class ServiceHasNoHealthyInstancesException(ProxyServiceException):
    """Exception raised when no healthy instance is found for a service."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.detail = f'No healthy instance found for service "{service_name}".'
        super().__init__(self.detail)


class NotEnoughPermissionsException(ProxyServiceException):
    """Exception raised when the user does not have enough permissions to access a service."""

    status_code = status.HTTP_403_FORBIDDEN

    def __init__(self, service_name: str, path: str | None = None, action: str | None = None) -> None:
        self.service_name = service_name
        self.path = path
        self.action = action
        if action and path:
            self.detail = (
                f'You do not have enough permissions to perform action "{action}" on service "{service_name}".'
            )
        elif path:
            self.detail = f'You do not have enough permissions to access "{path}" of service "{service_name}".'
        else:
            self.detail = f'You do not have enough permissions to access service "{service_name}".'
        super().__init__(self.detail)


class ProxyStaticFileException(ProxyServiceException):
    """Exception raised when there is an error proxying a static file."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail = 'An error occurred while proxying the static file.'


class ServiceHasNoEndpointsException(ProxyServiceException):
    """Exception raised when a service has no endpoints defined."""

    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.detail = f'Service "{service_name}" has no endpoints defined.'
        super().__init__(self.detail)


class ServiceEndpointNotFoundException(ProxyServiceException):
    """Exception raised when a service endpoint is not found."""

    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, service_name: str, endpoint: str) -> None:
        self.service_name = service_name
        self.endpoint = endpoint
        self.detail = f'Endpoint "{endpoint}" not found in service "{service_name}".'
        super().__init__(self.detail)


class ProxyOpaClientInitException(ProxyServiceException):
    """Exception raised when there is an error initializing the OPA client."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail = 'An error occurred while initializing the OPA client.'


# OPA Client Errors
class OpaClientException(GatewayException):
    """Base exception for OPA client errors."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail: str = 'An error occurred while communicating with the OPA server.'


class OpaRequestException(OpaClientException):
    """Exception raised when there is an error making a request to the OPA server."""

    detail: str = 'An error occurred while making a request to the OPA server.'


class OpaResponseFormatException(OpaClientException):
    """Exception raised when the OPA server response format is invalid."""

    detail: str = 'Invalid OPA response format.'


# Keycloak OIDC Errors
class KeycloakOIDCException(GatewayException):
    """Base class for Keycloak OIDC errors."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail: str = 'An error occurred while processing Keycloak OIDC operations.'


class AuthorizationUrlException(KeycloakOIDCException):
    """Exception raised when the Keycloak OIDC authorization endpoint is not configured."""

    status_code = status.HTTP_401_UNAUTHORIZED
    detail = 'Authorization URL not found in OIDC config. Please check your Keycloak OIDC settings.'


class TokenUrlException(KeycloakOIDCException):
    """Exception raised when the Keycloak OIDC token endpoint is not configured."""

    status_code = status.HTTP_401_UNAUTHORIZED
    detail = 'Token URL not found in OIDC config. Please check your Keycloak OIDC settings.'


class IssuerException(KeycloakOIDCException):
    """Exception raised when the Keycloak OIDC issuer is not configured."""

    status_code = status.HTTP_401_UNAUTHORIZED
    detail = 'Issuer not found in OIDC config. Please check your Keycloak OIDC settings.'


class OIDCConfigFetchException(KeycloakOIDCException):
    """Exception raised when there is an error fetching the OIDC config."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    detail = 'Error fetching OIDC config. Keycloak server is unavailable.'


class OIDCConfigTimeoutException(KeycloakOIDCException):
    """Exception raised when there is a timeout fetching the OIDC config."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    detail = 'Timeout error fetching OIDC config. Keycloak server is unavailable.'


class OIDCConfigUnexpectedException(KeycloakOIDCException):
    """Exception raised for unexpected errors fetching the OIDC config."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail = 'Unexpected error fetching OIDC config'


class JWKSKeyNotFoundException(KeycloakOIDCException):
    """Exception raised when a key is not found in JWKS."""

    status_code = status.HTTP_401_UNAUTHORIZED
    detail = 'Key not found in JWKS.'


class JWKSUriNotFoundException(KeycloakOIDCException):
    """Exception raised when JWKS URI is not found in OIDC config."""

    status_code = status.HTTP_401_UNAUTHORIZED
    detail = 'JWKS URI not found in OIDC config.'


class JWKSFetchException(KeycloakOIDCException):
    """Exception raised when there is an error fetching JWKS."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    detail = 'Error fetching JWKS. Keycloak server is unavailable.'


class JWKSFetchTimeoutException(KeycloakOIDCException):
    """Exception raised when there is a timeout fetching JWKS."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    detail = 'Timeout error fetching JWKS. Keycloak server is unavailable.'


class AuthorizationHeaderInvalidException(KeycloakOIDCException):
    """Exception raised when the authorization header is missing or invalid."""

    status_code = status.HTTP_401_UNAUTHORIZED
    detail = 'Authorization header is missing or invalid.'


class JWTDecodeHeaderException(KeycloakOIDCException):
    """Exception raised when there is a decode error for JWT token header."""

    status_code = status.HTTP_401_UNAUTHORIZED
    detail = 'Decode error for JWT token header.'


class JWTKidNotFoundException(KeycloakOIDCException):
    """Exception raised when KID is not found in token."""

    status_code = status.HTTP_401_UNAUTHORIZED
    detail = 'KID not found in token.'


class JWTExpiredException(KeycloakOIDCException):
    """Exception raised when the token has expired."""

    status_code = status.HTTP_401_UNAUTHORIZED
    detail = 'Token has expired'


class JWTInvalidTokenException(KeycloakOIDCException):
    """Exception raised when the token is invalid."""

    status_code = status.HTTP_401_UNAUTHORIZED
    detail = 'Invalid token'


class JWTValidationException(KeycloakOIDCException):
    """Exception raised when there is a token validation error."""

    status_code = status.HTTP_401_UNAUTHORIZED
    detail = 'Token validation error'


# WebSocket Errors
class SecureWebSocketException(WebSocketException):
    """Base class for secure WebSocket errors."""

    status_code = status.WS_1011_INTERNAL_ERROR
    detail: str = 'An unexpected error occurred in the secure WebSocket connection.'

    def __init__(self, detail: str | None = None) -> None:
        if detail:
            self.detail = detail
        super().__init__(code=self.status_code, reason=self.detail)


class SecureWebSocketPolicyException(SecureWebSocketException):
    """Generic error means message violates policy of socket"""

    status_code = status.WS_1008_POLICY_VIOLATION
    detail: str = 'WebSocket policy violation occurred.'


class SecureWebSocketServerException(SecureWebSocketException):
    """Unexpected conditions prevents from fulfilling a request"""

    status_code = status.WS_1011_INTERNAL_ERROR
    detail: str = 'Internal server error in secure WebSocket connection.'
