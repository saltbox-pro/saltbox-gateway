import json
from typing import Any, cast

from saltbox_gateway.services.discovery import DiscoveryService
from saltbox_gateway.tmp_ws_proxy.errors import JobDoesNotExistsException, JobMultipleReturnsException
from saltbox_gateway.tmp_ws_proxy.schemas import JOB_CREATE_HASH_NAME, JobData, JobModel
from saltbox_gateway.tmp_ws_proxy.utils import JID
from saltbox_gateway.utils.httpx_client import HttpxClientSingletoneFactory
from saltbox_gateway.utils.redis_config import RedisDependency


class JobDao:
    def __init__(self, rdb: RedisDependency) -> None:
        self.rdb = rdb

    async def _get_job_data_from_store(self, jid: JID) -> JobData | None:
        ts = jid.to_timestamp()
        job_data = await self.rdb.zrange('jobs', start=ts, end=ts, byscore=True)  # type: ignore[call-overload]

        if job_data:
            if len(job_data) > 1:
                msg = f'Multiple jobs for JID {jid}'
                raise JobMultipleReturnsException(msg)

            res: dict[str, Any] = json.loads(job_data[0])
            res['status'] = JobModel.JobStatus.started

            return res

        return None

    async def _get_job_data_from_queue(self, job_hash_name: str) -> dict[str, Any] | None:
        job_data: dict[bytes, bytes] = await self.rdb.hgetall(job_hash_name)

        if job_data:
            return {
                'jid': job_data[b'jid'].decode()[:20],
                'tgt': job_data[b'tgt'].decode(),
                'tgt_type': job_data[b'tgt_type'].decode(),
                'fun': job_data[b'fun'].decode(),
                'arg': json.loads(job_data[b'arg']) if b'arg' in job_data else None,
                'kwarg': json.loads(job_data[b'kwarg']) if b'kwarg' in job_data else None,
                'status': JobModel.JobStatus.in_queue,
            }
        return None

    async def get_job(self, jid: JID) -> JobModel:
        job_data = await self._get_job_data_from_store(jid)

        if not job_data:
            job_data = await self._get_job_data_from_queue(JOB_CREATE_HASH_NAME.format(jid=str(jid)))

        if not job_data:
            msg = 'Job not found'
            raise JobDoesNotExistsException(msg)
        else:
            return JobModel(**job_data)


class TaskDao:
    def __init__(self, rdb: RedisDependency, discovery: DiscoveryService) -> None:
        self.rdb = rdb
        self._httpx_client = HttpxClientSingletoneFactory.get_instance()
        self._discovery = discovery

    async def get(self, tid: str) -> dict | None:
        core_service = await self._discovery.get_service_by_name('core')
        instance = next(inst for inst in core_service.instances if inst.healthy)

        result = await self._httpx_client.get(
            f'http://{instance.host}:{instance.port}/tasks/{tid}',
        )
        if result.status_code != 200:
            return None
        return cast(dict, result)
