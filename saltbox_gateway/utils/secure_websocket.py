import asyncio
import datetime
import functools
import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from types import TracebackType
from typing import Any, TypedDict, cast

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from saltbox_gateway.config import logger
from saltbox_gateway.exceptions import KeycloakOIDCException
from saltbox_gateway.utils.keycloak_oidc import KeycloakOIDCFactory
from saltbox_sdk.db.schemas_base import User


class RedisPubSubMessage(TypedDict):
    type: str
    pattern: str | None
    channel: str
    data: bytes


class IsSocketDisconnected(AbstractContextManager):
    """
    Supress WebSocketDisconnect error
    """

    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.is_excepted = False

    def __enter__(self) -> 'IsSocketDisconnected':
        return self

    def __exit__(
        self,
        exttype: type[BaseException] | None,
        extint: BaseException | None,
        exttb: TracebackType | None,
    ) -> bool:
        if exttype is None:
            return True
        if issubclass(exttype, WebSocketDisconnect):
            self.is_excepted = True
            return True
        return False

    def __bool__(self) -> bool:
        return self.is_excepted


def _check_ws_connection(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator to check secure WebSocket connection state
    Raises WebSocketDisconnect if token expired or WebSocket disconnected
    """

    @functools.wraps(fn)
    async def wrapper(self: 'AuthenticatedWebSocket', *args: tuple, **kwargs: dict) -> Any:
        if self._already_closed:
            raise WebSocketDisconnect
        if self.token_expiration and datetime.datetime.now(datetime.UTC) >= self.token_expiration:
            await self.close('Token expired')
            raise WebSocketDisconnect
        return await fn(self, *args, **kwargs)

    return wrapper


class AuthenticatedWebSocket:
    """Base class for authenticated WebSocket connections

    Example:
    @router.websocket('')
    async def ws_endpoint(websocket: WebSocket) -> None:
        secure_websocket = AuthenticatedWebSocket(websocket)
        await secure_websocket.accept()
        logger.info('Start sending messages')

        while True:
            try:
                await secure_websocket.send('Hello')
                await asyncio.sleep(3)
            except WebSocketDisconnect:
                break
    """

    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.token_expiration: datetime.datetime | None = None
        self._subtasks: set[asyncio.Task] = set()
        self._oidc = KeycloakOIDCFactory.get_instance()
        self.user: User | None = None

    @property
    def _already_closed(self) -> bool:
        return (
            self.websocket.application_state == WebSocketState.DISCONNECTED
            or self.websocket.client_state == WebSocketState.DISCONNECTED
        )

    @_check_ws_connection
    async def _obtain_token_msg(self) -> None:
        message = await self.websocket.receive_text()
        # TODO (a.baikov): temporary solution until we get full token from client
        message = 'Bearer ' + message
        await self._process_token_message(message)

    async def _process_token_message(self, token: str) -> None:
        try:
            payload = await self._oidc.decode_jwt(token)
            self.user = User.model_validate(payload)
            exp = cast(float, payload.get('exp'))
            self.token_expiration = datetime.datetime.fromtimestamp(exp, datetime.UTC)
        except KeycloakOIDCException as e:
            logger.error('Error processing token message %s', e)
            await self.close(f'Invalid token message: {e!s}')

    async def accept(self) -> None:
        try:
            await self.websocket.accept()
            await self._obtain_token_msg()
        except WebSocketDisconnect:
            await self.close('WebSocket disconnected')

        self._subtasks.add(asyncio.create_task(self._token_refresher_task_manager()))

    async def _token_refresher_task_manager(self) -> None:
        while not self._already_closed:
            token_refresher_task = asyncio.create_task(self._token_refresher())
            self._subtasks.add(token_refresher_task)
            try:
                await token_refresher_task
            except WebSocketDisconnect:
                await self.close('WebSocket disconnected')
            except Exception as e:
                logger.error('Error in _token_refresher_task: %s', e)
            finally:
                self._subtasks.remove(token_refresher_task)
                token_refresher_task.cancel()
                await asyncio.sleep(1)

    @_check_ws_connection
    async def send_text(self, message: str) -> None:
        await self.websocket.send_text(message)

    async def _token_refresher(self) -> None:
        while not self._already_closed:
            await self._obtain_token_msg()

    async def close(self, msg: str) -> None:
        for task in self._subtasks:
            task.cancel()

        if not self._already_closed:
            await self.websocket.close(code=1008, reason=msg)


class PubSubMessageHandler:
    def __init__(
        self,
        channel: str,
        message_tag: str,
        *,
        send_empty: bool = False,
        schema: type[BaseModel] | None = None,
        callback: Callable | None = None,
    ) -> None:
        self.channel = channel
        self.message_tag = message_tag
        self.send_empty = send_empty

        if schema is None and callback is None:
            msg = 'Must provide schema or callback'
            raise ValueError(msg)
        elif schema is not None and callback is not None:
            msg = 'Must provide only schema or only callback at same time'
            raise ValueError(msg)

        self.schema = schema
        self.callback = callback

    async def _handle_message_by_schema(self, message: RedisPubSubMessage) -> Any:
        if self.schema is None:
            msg = 'Must provide schema'
            raise ValueError(msg)

        data_str = message['data'].decode()
        try:
            data = json.loads(data_str)
            instance = self.schema(**data)
            return instance.model_dump(by_alias=True, mode='json')
        except (ValidationError, TypeError, json.JSONDecodeError) as e:
            logger.error(
                'Error processing pubsub message from channel "%s"\nMessage: %s\nError: %s\n---',
                message['channel'],
                e,
                data_str,
            )

        return None

    async def _handle_message_by_callback(self, message: RedisPubSubMessage) -> Any:
        if self.callback is None:
            msg = 'Must provide callback'
            raise ValueError(msg)

        data_str = message['data'].decode()
        try:
            data = json.loads(data_str)
            result = self.callback(data=data)

            if result is not None:
                return result
        except (ValidationError, TypeError, json.JSONDecodeError) as e:
            logger.error(
                'Error processing pubsub message from channel "%s"\nMessage: %s\nError: %s\n---',
                message['channel'],
                e,
                data_str,
            )

        return None

    async def handle_message(self, message: RedisPubSubMessage) -> Any:
        if self.schema:
            return await self._handle_message_by_schema(message)
        elif self.callback:
            return await self._handle_message_by_callback(message)

        return None


class PubSubAuthenticatedWebSocket(AuthenticatedWebSocket):
    """WebSocket connection for PubSub messages forwarding

    Example:
    @ws_router.websocket('/pubsub')
    async def channel_forwarder(websocket: WebSocket, rdb: RedisDependency) -> None:
        secure_websocket = PubSubAuthenticatedWebSocket(websocket, rdb)

        await secure_websocket.handle_pubsub({'job:*:create': Job, 'channel2': AnotherModel})
    """

    def __init__(self, websocket: WebSocket, rdb: Redis) -> None:
        super().__init__(websocket)
        self._rdb = rdb

    async def _message_forwarder(self, handler: PubSubMessageHandler) -> None:
        async with self._rdb.pubsub() as pubsub:
            await pubsub.psubscribe(handler.channel)
            async for message in pubsub.listen():
                if self._already_closed:
                    break
                if message['type'] not in PubSub.PUBLISH_MESSAGE_TYPES:
                    continue

                handler_result = await handler.handle_message(message)

                if handler_result or handler.send_empty:
                    await self.send_text(json.dumps({'message_tag': handler.message_tag, 'payload': handler_result}))

    async def handle_pubsub(self, handlers: list[PubSubMessageHandler]) -> None:
        await self.accept()
        channel_tasks = []
        for handler in handlers:
            task = asyncio.create_task(self._message_forwarder(handler))
            channel_tasks.append(task)
            self._subtasks.add(task)

        try:
            await asyncio.gather(*channel_tasks)
        except WebSocketDisconnect:
            await self.close('WebSocket disconnected')
        except asyncio.CancelledError:
            pass
