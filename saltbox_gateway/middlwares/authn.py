import re
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from saltbox_gateway.config import logger
from saltbox_gateway.exceptions import KeycloakOIDCException
from saltbox_gateway.utils.keycloak_oidc import KeycloakOIDCFactory
from saltbox_sdk.db.schemas_base import ANONYMOUS_USER, User

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        excluded_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        logger.debug('Initializing AuthMiddleware.')
        self._oidc = KeycloakOIDCFactory.get_instance()
        self._excluded = [re.compile(f'^{p}$') for p in (excluded_paths or [])]

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # logger.debug('\n\n\n\n====================\n')
        logger.debug('Dispatching request: %s', request.url.path)

        try:
            if self._is_excluded(request.url.path) or request.method == 'OPTIONS':
                request.state.user = ANONYMOUS_USER
                return await call_next(request)

            token = request.headers.get('Authorization')
            try:
                decoded = await self._oidc.decode_jwt(token)
                user = User.model_validate(decoded)
            except ValidationError:
                return JSONResponse(status_code=401, content={'detail': 'Token validation error'})
            except KeycloakOIDCException as e:
                return JSONResponse(status_code=e.status_code, content={'detail': e.detail})

            request.state.user = user
            logger.warning('User added to request state: %s', user.name)
            return await call_next(request)
        finally:
            request.state.user = None

    def _is_excluded(self, path: str) -> bool:
        return any(p.match(path) for p in self._excluded)
