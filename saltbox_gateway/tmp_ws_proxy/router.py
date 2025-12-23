from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket
from redis.asyncio import Redis

from saltbox_gateway.exceptions import SecureWebSocketPolicyException
from saltbox_gateway.services.discovery import DiscoveryService, get_discovery_service
from saltbox_gateway.tmp_ws_proxy.dao import JobDao, TaskDao
from saltbox_gateway.tmp_ws_proxy.schemas import IntJid, JobModel, JobReturnModel, TaskModel
from saltbox_gateway.tmp_ws_proxy.utils import JID
from saltbox_gateway.utils.opa_client import get_opa_client
from saltbox_gateway.utils.secure_websocket import PubSubAuthenticatedWebSocket, PubSubMessageHandler
from saltbox_sdk.db.redis.config import get_redis

ws_core_jobs_router = APIRouter(prefix='/api/core/jobs')
ws_core_tasks_router = APIRouter(prefix='/api/core/tasks')


@ws_core_jobs_router.websocket('')
async def jobs_rets_websocket(
    websocket: WebSocket,
    rdb: Annotated[Redis, Depends(get_redis)],
) -> None:
    secure_websocket = PubSubAuthenticatedWebSocket(websocket, rdb)
    await secure_websocket.handle_pubsub(
        handlers=[
            PubSubMessageHandler('job:*:create', 'job', schema=JobModel),
            PubSubMessageHandler('job:*:update', 'job', schema=JobModel),
        ]
    )


@ws_core_jobs_router.websocket('/{jid}/info')
async def job_info_endpoint_websocket(
    jid: IntJid,
    websocket: WebSocket,
    rdb: Annotated[Redis, Depends(get_redis)],
    discovery: Annotated[DiscoveryService, Depends(get_discovery_service)],
) -> None:
    _jid = JID(jid)
    job_service = JobDao(discovery)
    job = job_service.get_job(_jid)

    if not job:
        msg = f'Job not found by JID={jid}'
        raise SecureWebSocketPolicyException(msg)

    secure_websocket = PubSubAuthenticatedWebSocket(websocket, rdb)
    await secure_websocket.handle_pubsub(
        handlers=[
            PubSubMessageHandler(f'job:{jid}:create', 'job', schema=JobModel),
            PubSubMessageHandler(f'job:{jid}:update', 'job', schema=JobModel),
        ]
    )


@ws_core_jobs_router.websocket('/{jid}/return')
async def jobs_endpoint_websocket(
    jid: IntJid,
    websocket: WebSocket,
    rdb: Annotated[Redis, Depends(get_redis)],
    discovery: Annotated[DiscoveryService, Depends(get_discovery_service)],
) -> None:
    _jid = JID(jid)
    job_service = JobDao(discovery)
    job = job_service.get_job(_jid)

    if not job:
        msg = f'Job not found by JID={jid}'
        raise SecureWebSocketPolicyException(msg)

    secure_websocket = PubSubAuthenticatedWebSocket(websocket, rdb)
    await secure_websocket.handle_pubsub(
        handlers=[
            PubSubMessageHandler(f'job-return:{jid}:create', 'job-return', schema=JobReturnModel),
            PubSubMessageHandler(f'job-return:{jid}:update', 'job-return', schema=JobReturnModel),
        ]
    )


@ws_core_tasks_router.websocket('')
async def tasks_websocket(
    websocket: WebSocket,
    rdb: Annotated[Redis, Depends(get_redis)],
) -> None:
    secure_websocket = PubSubAuthenticatedWebSocket(websocket, rdb)
    await secure_websocket.handle_pubsub(
        handlers=[
            PubSubMessageHandler('task:*:create', 'task', schema=TaskModel),
            PubSubMessageHandler('task:*:update', 'task', schema=TaskModel),
        ]
    )


@ws_core_tasks_router.websocket('/{tid}')
async def task_websocket(
    tid: str,
    websocket: WebSocket,
    rdb: Annotated[Redis, Depends(get_redis)],
    discovery: Annotated[DiscoveryService, Depends(get_discovery_service)],
) -> None:
    task_service = TaskDao(discovery)
    task = await task_service.get_task(tid=tid)

    if not task:
        msg = f'Task not found by ID={tid}'
        raise SecureWebSocketPolicyException(msg)

    secure_websocket = PubSubAuthenticatedWebSocket(websocket, rdb)
    await secure_websocket.handle_pubsub(
        handlers=[
            PubSubMessageHandler(f'task:{tid}:job-return:*:create', 'job-return', schema=JobReturnModel),
            PubSubMessageHandler(f'task:{tid}:job-return:*:update', 'job-return', schema=JobReturnModel),
            PubSubMessageHandler(f'task:{tid}:job:*:create', 'job', schema=JobModel),
            PubSubMessageHandler(f'task:{tid}:job:*:update', 'job', schema=JobModel),
            PubSubMessageHandler(f'task:{tid}:update', 'task', schema=TaskModel),
        ]
    )


# New WebSocket endpoint implementation (temporary not used)
@ws_core_tasks_router.websocket('/new')
async def tasks_websocket_new(
    websocket: WebSocket,
    rdb: Annotated[Redis, Depends(get_redis)],
) -> None:
    opa_client = get_opa_client()
    secure_websocket = PubSubAuthenticatedWebSocket(websocket, rdb)
    if not secure_websocket.user:
        msg = 'User not authenticated'
        raise SecureWebSocketPolicyException(msg)
    _opa_result = await opa_client.check_policy(
        package='core.tasks',
        input={
            'user': secure_websocket.user.model_dump(),
            'path': ['api', 'core', 'tasks'],
        },
    )
    await secure_websocket.handle_pubsub(
        handlers=[
            PubSubMessageHandler(f'task:{secure_websocket.user.sub}:*:create', 'task', schema=TaskModel),
            PubSubMessageHandler(f'task:{secure_websocket.user.sub}*:update', 'task', schema=TaskModel),
        ]
    )
