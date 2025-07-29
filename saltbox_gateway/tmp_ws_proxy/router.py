from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket

from saltbox_gateway.config import logger
from saltbox_gateway.errors import SecureWebSocketPolicyViolation
from saltbox_gateway.services.discovery import DiscoveryService, get_discovery_service
from saltbox_gateway.tmp_ws_proxy.dao import JobDao, TaskDao
from saltbox_gateway.tmp_ws_proxy.errors import JobDoesNotExistsException
from saltbox_gateway.tmp_ws_proxy.schemas import IntJid, JobModel, JobResult, TaskModel
from saltbox_gateway.tmp_ws_proxy.utils import JID
from saltbox_gateway.utils.opa_client import get_opa_client
from saltbox_gateway.utils.redis_config import RedisDependency
from saltbox_gateway.utils.secure_websocket import PubSubAuthenticatedWebSocket

ws_core_jobs_router = APIRouter(prefix='/api/core/jobs')
ws_core_tasks_router = APIRouter(prefix='/api/core/tasks')


@ws_core_jobs_router.websocket('')
async def jobs_rets_websocket(websocket: WebSocket, rdb: RedisDependency) -> None:
    def job_new_handler(data: dict) -> str:
        return JobModel(**{'status': JobModel.JobStatus.started, **data}).model_dump_json(by_alias=True)

    secure_websocket = PubSubAuthenticatedWebSocket(websocket, rdb)
    await secure_websocket.handle_pubsub({'job:*:new': job_new_handler})


@ws_core_jobs_router.websocket('/{jid}/return')
async def jobs_endpoint_websocket(
    jid: IntJid,
    websocket: WebSocket,
    rdb: RedisDependency,
) -> None:
    _jid = JID(jid)
    job_service = JobDao(rdb)

    try:
        await job_service.get_job(_jid)
    except JobDoesNotExistsException as e:
        msg = f'Job not found by JID={jid}'
        raise SecureWebSocketPolicyViolation(msg) from e

    secure_websocket = PubSubAuthenticatedWebSocket(websocket, rdb)
    await secure_websocket.handle_pubsub({f'job:{jid}:return': JobResult})


@ws_core_tasks_router.websocket('')
async def tasks_websocket(websocket: WebSocket, rdb: RedisDependency) -> None:
    secure_websocket = PubSubAuthenticatedWebSocket(websocket, rdb)
    await secure_websocket.handle_pubsub(
        {
            'task:*:create': TaskModel,
            'task:*:update': TaskModel,
        }
    )


@ws_core_tasks_router.websocket('/{tid}')
async def task_websocket(
    tid: str,
    websocket: WebSocket,
    rdb: RedisDependency,
    discovery: Annotated[DiscoveryService, Depends(get_discovery_service)],
) -> None:
    task_service = TaskDao(rdb, discovery)
    task = await task_service.get(tid=tid)

    logger.warning(f'Task {tid} found: {task}')

    if not task:
        msg = f'Task not found by ID={tid}'
        raise SecureWebSocketPolicyViolation(msg)

    def job_new_handler(data: dict) -> str:
        return JobModel(**{'status': JobModel.JobStatus.started, **data}).model_dump_json(by_alias=True)

    secure_websocket = PubSubAuthenticatedWebSocket(websocket, rdb)
    await secure_websocket.handle_pubsub(
        {
            f'task:{tid}:job:*:return': JobResult,
            f'task:{tid}:job:*:new': job_new_handler,
            f'task:{tid}:update': TaskModel,
        }
    )


# New WebSocket endpoint implementation (temporary not used)
@ws_core_tasks_router.websocket('/new')
async def tasks_websocket_new(websocket: WebSocket, rdb: RedisDependency) -> None:
    opa_client = get_opa_client()
    secure_websocket = PubSubAuthenticatedWebSocket(websocket, rdb)
    if not secure_websocket.user:
        msg = 'User not authenticated'
        raise SecureWebSocketPolicyViolation(msg)
    _opa_result = await opa_client.check_policy(
        package='core.tasks',
        input={
            'user': secure_websocket.user.model_dump(),
            'path': ['api', 'core', 'tasks'],
        },
    )
    await secure_websocket.handle_pubsub(
        {
            f'task:{secure_websocket.user.sub}:*:create': TaskModel,
            f'task:{secure_websocket.user.sub}*:update': TaskModel,
        }
    )
