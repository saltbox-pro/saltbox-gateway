from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket
from redis.asyncio import Redis

from saltbox_gateway.exceptions import SecureWebSocketPolicyException
from saltbox_gateway.services.discovery import DiscoveryService, get_discovery_service
from saltbox_gateway.tmp_ws_proxy.dao import JobDao, TaskDao
from saltbox_gateway.tmp_ws_proxy.schemas import JobModel, JobReturnNotifySchema, TaskMinionModel, TaskModel
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


@ws_core_jobs_router.websocket('/{job_id}/info')
async def job_info_endpoint_websocket(
    job_id: str,
    websocket: WebSocket,
    rdb: Annotated[Redis, Depends(get_redis)],
    discovery: Annotated[DiscoveryService, Depends(get_discovery_service)],
) -> None:
    job_service = JobDao(discovery)
    job = await job_service.get_job(job_id=job_id)

    if not job:
        msg = f'Job not found by mongo ID={job_id}'
        raise SecureWebSocketPolicyException(msg)

    secure_websocket = PubSubAuthenticatedWebSocket(websocket, rdb)
    await secure_websocket.handle_pubsub(
        handlers=[
            PubSubMessageHandler(f'job:{job_id}:create', 'job', schema=JobModel),
            PubSubMessageHandler(f'job:{job_id}:update', 'job', schema=JobModel),
            PubSubMessageHandler(f'job-return:{job_id}:create', 'job-return', schema=JobReturnNotifySchema),
            PubSubMessageHandler(f'job-return:{job_id}:update', 'job-return', schema=JobReturnNotifySchema),
        ]
    )


@ws_core_jobs_router.websocket('/{job_id}/return')
async def jobs_endpoint_websocket(
    job_id: str,
    websocket: WebSocket,
    rdb: Annotated[Redis, Depends(get_redis)],
    discovery: Annotated[DiscoveryService, Depends(get_discovery_service)],
) -> None:
    job_service = JobDao(discovery)
    job = await job_service.get_job(job_id=job_id)

    if not job:
        msg = f'Job not found by mongo ID={job_id}'
        raise SecureWebSocketPolicyException(msg)

    secure_websocket = PubSubAuthenticatedWebSocket(websocket, rdb)
    await secure_websocket.handle_pubsub(
        handlers=[
            PubSubMessageHandler(f'job-return:{job_id}:create', 'job-return', schema=JobReturnNotifySchema),
            PubSubMessageHandler(f'job-return:{job_id}:update', 'job-return', schema=JobReturnNotifySchema),
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


@ws_core_tasks_router.websocket('/{task_id}')
async def task_websocket(
    task_id: str,
    websocket: WebSocket,
    rdb: Annotated[Redis, Depends(get_redis)],
    discovery: Annotated[DiscoveryService, Depends(get_discovery_service)],
) -> None:
    task_service = TaskDao(discovery)
    task = await task_service.get_task(task_id=task_id)

    if not task:
        msg = f'Task not found by mongo ID={task_id}'
        raise SecureWebSocketPolicyException(msg)

    secure_websocket = PubSubAuthenticatedWebSocket(websocket, rdb)
    await secure_websocket.handle_pubsub(
        handlers=[
            PubSubMessageHandler(f'task:{task_id}:job-return:*:create', 'job-return', schema=JobReturnNotifySchema),
            PubSubMessageHandler(f'task:{task_id}:job-return:*:update', 'job-return', schema=JobReturnNotifySchema),
            PubSubMessageHandler(f'task:{task_id}:task-minion:*:create', 'task-minion', schema=TaskMinionModel),
            PubSubMessageHandler(f'task:{task_id}:task-minion:*:update', 'task-minion', schema=TaskMinionModel),
            PubSubMessageHandler(f'task:{task_id}:update', 'task', schema=TaskModel),
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
