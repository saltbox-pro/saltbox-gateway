from typing import cast

from saltbox_gateway.services.discovery import DiscoveryService
from saltbox_gateway.tmp_ws_proxy.schemas import JobModel
from saltbox_gateway.tmp_ws_proxy.utils import JID
from saltbox_gateway.utils.httpx_client import HttpxClientSingletoneFactory


class JobDao:
    def __init__(self, discovery: DiscoveryService) -> None:
        self._httpx_client = HttpxClientSingletoneFactory.get_instance()
        self._discovery = discovery

    async def get_job(self, jid: JID) -> JobModel | None:
        core_service = await self._discovery.get_service_by_name('core')
        instance = next(inst for inst in core_service.instances if inst.healthy)

        result = await self._httpx_client.get(
            f'http://{instance.host}:{instance.port}/jobs/{jid!s}',
        )

        if result.status_code != 200:
            return None

        return JobModel(**cast(dict, result.json()))


class TaskDao:
    def __init__(self, discovery: DiscoveryService) -> None:
        self._httpx_client = HttpxClientSingletoneFactory.get_instance()
        self._discovery = discovery

    async def get_task(self, tid: str) -> dict | None:
        core_service = await self._discovery.get_service_by_name('core')
        instance = next(inst for inst in core_service.instances if inst.healthy)

        result = await self._httpx_client.get(
            f'http://{instance.host}:{instance.port}/tasks/{tid}',
        )
        if result.status_code != 200:
            return None
        return cast(dict, result.json())
