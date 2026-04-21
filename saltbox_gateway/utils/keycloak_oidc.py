import json
import time
from contextvars import ContextVar
from typing import Any, cast

import httpx
import jwt
from fastapi import Request
from pydantic import ValidationError

from saltbox_gateway.config import logger
from saltbox_gateway.exceptions import (
    AuthorizationHeaderInvalidException,
    AuthorizationUrlException,
    IssuerException,
    JWKSFetchException,
    JWKSFetchTimeoutException,
    JWKSKeyNotFoundException,
    JWKSUriNotFoundException,
    JWTDecodeHeaderException,
    JWTExpiredException,
    JWTInvalidTokenException,
    JWTKidNotFoundException,
    JWTValidationException,
    KeycloakOIDCException,
    OIDCConfigFetchException,
    OIDCConfigTimeoutException,
    OIDCConfigUnexpectedException,
    TokenUrlException,
)
from saltbox_gateway.utils.httpx_client import HttpxClientSingletoneFactory
from saltbox_gateway.utils.redis_cache import BaseCache, CustomRedisCache
from saltbox_gateway.utils.redis_config import get_redis_connection
from saltbox_sdk.config.keycloak_config import KC_SETTINGS

request_context: ContextVar[Request] = ContextVar('request_context')


class KeycloakOIDC:
    """Keycloak OIDC client"""

    def __init__(
        self,
        *,
        audience: str = 'account',
        httpx_client: httpx.AsyncClient | None = None,
        cache: BaseCache | None = None,
    ) -> None:
        logger.debug('Initializing KeycloakOIDC instance.')
        self._oidc_url = KC_SETTINGS.oidc_url
        self._httpx_client = httpx_client or httpx.AsyncClient()
        self._cache = cache
        self._issuer: str | None = None
        self._audience = audience
        self._algorithms = ['RS256']
        self._token_url: str | None = None
        self._authorization_endpoint: str | None = None

    @property
    def authorization_endpoint(self) -> str:
        if not self._authorization_endpoint:
            raise AuthorizationUrlException()

        return self._authorization_endpoint

    @property
    def token_url(self) -> str:
        if not self._token_url:
            raise TokenUrlException()

        return self._token_url

    async def _get_oidc_config(self) -> dict[str, Any]:
        """Get OIDC configuration from Keycloak server and cache it.

        Returns:
            dict[str, Any]: OIDC configuration.
        """
        if self._cache:
            oidc_config = await self._cache.get(self._oidc_url)
            if oidc_config:
                return cast(dict[str, Any], json.loads(oidc_config))

        try:
            response = await self._httpx_client.get(self._oidc_url)
            response.raise_for_status()

            oidc_config = response.json()
            self._issuer = oidc_config.get('issuer')
            if not self._issuer:
                raise IssuerException()

            self._algorithms = oidc_config.get('id_token_signing_alg_values_supported', self._algorithms)

            if self._cache:
                await self._cache.set(self._oidc_url, json.dumps(oidc_config), 3600)
            return cast(dict, oidc_config)
        except httpx.HTTPStatusError as e:
            logger.exception('Error fetching OIDC config: %s', e)
            raise OIDCConfigFetchException() from None
        except httpx.ReadTimeout as e:
            logger.exception('Timeout error fetching OIDC config: %s', e)
            raise OIDCConfigTimeoutException() from None
        except Exception as e:
            logger.error('Unexpected error fetching OIDC config: %s', e)
            raise OIDCConfigUnexpectedException() from None

    async def _get_key_by_kid(self, token_kid: str) -> jwt.PyJWK:
        """Get the public key by KID from the JWKS and cache it.

        Args:
            token_kid (str): The KID of the token.

        Returns:
            jwt.PyJWK: The public key.
        """
        if self._cache:
            cached_key = await self._cache.get(token_kid)
            if cached_key:
                return jwt.PyJWK(json.loads(cached_key))

        jwks = await self._get_jwks()
        public_keys = {key['kid']: key for key in jwks['keys']}
        if token_kid not in public_keys:
            raise JWKSKeyNotFoundException()

        if self._cache:
            await self._cache.set(token_kid, json.dumps(public_keys[token_kid]), 3600)
        return jwt.PyJWK(public_keys[token_kid])

    async def _get_jwks(self) -> dict[str, Any]:
        """Get the JWKS from the OIDC configuration and cache it.

        Returns:
            dict[str, Any]: The JWKS.
        """
        oidc_config = await self._get_oidc_config()
        jwks_uri = oidc_config.get('jwks_uri')
        if not jwks_uri:
            raise JWKSUriNotFoundException()

        if self._cache:
            cached_jwks = await self._cache.get(jwks_uri)
            if cached_jwks:
                return cast(dict[str, Any], json.loads(cached_jwks))

        try:
            response = await self._httpx_client.get(jwks_uri)
            response.raise_for_status()

            jwks = response.json()

            if self._cache:
                await self._cache.set(jwks_uri, json.dumps(jwks), 3600)
            return cast(dict[str, Any], jwks)
        except httpx.HTTPStatusError as e:
            logger.exception('Error fetching JWKS: %s', e)
            raise JWKSFetchException() from None
        except httpx.ReadTimeout as e:
            logger.exception('Timeout error fetching JWKS: %s', e)
            raise JWKSFetchTimeoutException() from None

    async def decode_jwt(self, token: str | None) -> dict[str, str | list[str]]:  # noqa: C901
        """Decode the JWT token and verify its signature.

        Args:
            token (str | None): The JWT token to decode.
        Returns:
            dict[str, str | list[str]]: The decoded token.
        Raises:
            KeycloakOIDCError: If the token is invalid or expired.
        """
        if not token or not token.startswith('Bearer '):
            raise AuthorizationHeaderInvalidException()
        token = token.removeprefix('Bearer').strip()

        if self._cache:
            cached_token = await self._cache.get(token)
            if cached_token:
                return cast(dict[str, str | list[str]], json.loads(cached_token))

        try:
            unverified_header = jwt.get_unverified_header(token)
        except jwt.DecodeError as e:
            logger.exception('Decode error for JWT token header: %s', e)
            raise JWTDecodeHeaderException() from None
        token_kid = unverified_header.get('kid')
        if not token_kid:
            raise JWTKidNotFoundException()

        pyjwk = await self._get_key_by_kid(token_kid)

        try:
            decoded_token = jwt.decode(
                token,
                key=pyjwk.key,
                issuer=self._issuer,
                algorithms=self._algorithms,
                audience=self._audience,
                options={
                    'verify_iss': True,
                    'verify_signature': True,
                    'verify_aud': True,
                    'verify_iat': True,
                    'require_exp': True,
                },
            )
            current_time = int(time.time())
            exp_time = decoded_token.get('exp', 0)
            ttl = max(0, exp_time - current_time)  # Ensure TTL is never negative

            if self._cache:
                await self._cache.set(token, json.dumps(decoded_token), ttl=ttl)
            return cast(dict[str, str | list[str]], decoded_token)
        except jwt.ExpiredSignatureError:
            raise JWTExpiredException() from None
        except jwt.InvalidTokenError as e:
            msg = f'Invalid token: {e!s}'
            raise JWTInvalidTokenException(msg) from None
        except ValidationError as e:
            msg = f'Token validation error: {e!s}'
            raise JWTValidationException(msg) from None
        except Exception as e:
            msg = f'Unexpected error during JWT decoding: {e!s}'
            raise KeycloakOIDCException(msg) from None


class KeycloakOIDCFactory:
    """Singleton factory for KeycloakOIDC."""

    _instance: KeycloakOIDC | None = None

    @classmethod
    def get_instance(cls) -> KeycloakOIDC:
        if cls._instance is None:
            httpx_client = HttpxClientSingletoneFactory.get_instance()
            redis = get_redis_connection()
            cache = CustomRedisCache(redis_client=redis, namespace='oidc', ttl=3600)
            cls._instance = KeycloakOIDC(httpx_client=httpx_client, cache=cache)
        return cls._instance
