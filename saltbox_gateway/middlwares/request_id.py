from collections.abc import Callable
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from saltbox_gateway.config import logger

request_id_var: ContextVar[str | None] = ContextVar('request_id', default=None)


def set_request_id(request_id: str) -> Any:
    return request_id_var.set(request_id)


def reset_request_id(token: Any) -> None:
    try:
        request_id_var.reset(token)
    except Exception as exc:
        logger.debug('request_id reset failed: %s', exc)


def get_request_id() -> str | None:
    return request_id_var.get()


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        req_id = request.headers.get('X-Request-Id') or request.headers.get('X-Request-ID')
        if not req_id:
            req_id = uuid4().hex
        # put into state for downstream use
        request.state.request_id = req_id
        token = set_request_id(req_id)
        try:
            response: Response = await call_next(request)
        finally:
            reset_request_id(token)
        if 'X-Request-Id' not in response.headers and 'X-Request-ID' not in response.headers:
            response.headers['X-Request-Id'] = req_id
        return response
