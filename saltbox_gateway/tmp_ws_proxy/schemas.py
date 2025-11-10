from datetime import datetime
from enum import Enum, StrEnum
from typing import Annotated, Any, Self, TypeVar

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PastDatetime,
    PlainSerializer,
    computed_field,
    model_validator,
)

from saltbox_gateway.tmp_ws_proxy.errors import JidError
from saltbox_gateway.tmp_ws_proxy.utils import (
    JID,
    fill_salt_kwarg_from_arg,
    format_iso8601_z,
    make_aware,
    utc_now,
)
from saltbox_sdk.db.schemas_base import SYSTEM_SHORT_USER, CreatedModifiedMixin, Source, UserShort

T = TypeVar('T')
JID_T = TypeVar('JID_T', str, int)
Iso8601ZDatetime = Annotated[
    datetime,
    AfterValidator(make_aware),
    PlainSerializer(format_iso8601_z, when_used='json'),
    'Aware datetime serializing with Z-suffix. Unaware datetime decides UTC.',
]


def jidable(value: JID_T) -> JID_T:  # noqa: UP047
    try:
        JID(value)
    except JidError as err:
        raise ValueError(err) from err
    return value


IntJid = Annotated[int, AfterValidator(jidable)]
StrJid = Annotated[str, AfterValidator(jidable)]
JobData = dict[str, Any]
JOB_CREATE_HASH_NAME: str = 'job_create:{jid}'


class JobStatus(StrEnum):
    in_queue = 'in_queue'
    started = 'started'
    waiting_returns = 'waiting_returns'
    finished = 'finished'


class JobModel(BaseModel, CreatedModifiedMixin):
    jid: StrJid
    tgt: str | list[str]
    tgt_type: str
    salt_master: str
    user: UserShort | None = Field(default=SYSTEM_SHORT_USER)
    system_user: str | None = None
    fun: str
    arg: list | None = None
    kwarg: dict | None = None
    minions: list[str] = Field(default=[])
    missing: list[str] = Field(default=[])
    returning: dict[str, bool | None] = Field(default={})
    stamp: str | None = Field(alias='_stamp', default=None)
    status: JobStatus = JobStatus.started
    source: Source | None = None

    @computed_field(title='Timestamp decoded from JID')
    def fms_jid_timestamp(self) -> Annotated[datetime, PastDatetime]:
        return JID(self.jid).to_datetime()

    @model_validator(mode='before')
    @classmethod
    def _extract_kwargs(cls, data: Any) -> Any:
        # data may be an instantiated Job or potentially any object
        if not isinstance(data, dict):
            return data

        data['arg'], data['kwarg'] = fill_salt_kwarg_from_arg(data.get('arg'), data.get('kwarg'))

        return data


class JobReturnModel(BaseModel, CreatedModifiedMixin):
    """
    Describes return data for a job
    """

    # Officially obligatory fields are only [ id, jid, retcode, fun, return ]
    # https://docs.saltproject.io/en/latest/topics/event/master_events.html#job-events
    model_config = ConfigDict(extra='allow')

    id: str

    minion_id: str
    salt_master: str
    retcode: int
    jid: StrJid
    fun: str
    fun_args: list | None = None
    fun_kwarg: dict | None = None
    user: UserShort | None = Field(default=SYSTEM_SHORT_USER)
    system_user: str | None = None
    stamp: str | None = None
    stamp_job: str | None = None
    source: Source | None = None
    data: Any | None = None

    @model_validator(mode='before')
    @classmethod
    def _extract_kwargs(cls, data: Any) -> Any:
        # data may be an instantiated Job or potentially any object
        if not isinstance(data, dict):
            return data

        data['fun_args'], data['fun_kwarg'] = fill_salt_kwarg_from_arg(data.get('fun_args'), data.get('fun_kwarg'))

        return data


# Task-related schemas


class TaskData(BaseModel):  # type: ignore[no-redef]
    args: list | None = Field(default=None)
    kwargs: dict | None = Field(default=None)


class TaskSource(BaseModel):
    type: str = Field(title='Source type')
    id: str | None = Field(title='Source id', default=None)


class TaskJobReturnStatus(str, Enum):
    succeeded = 'succeeded'
    failed = 'failed'
    waiting = 'waiting'
    timeout = 'timeout'


class TaskJobStatus(str, Enum):
    pending = 'pending'
    running = 'running'
    succeeded = 'succeeded'
    failed = 'failed'


class TaskJobTargetType(str, Enum):
    list = 'list'
    compound = 'compound'


class TaskJobTarget(BaseModel):
    tgt: str = Field(title='Salt tgt')
    tgt_type: TaskJobTargetType = Field(title='Salt tgt type')
    master: str = Field(title='Master')


class TaskJob(BaseModel):
    jid: str = Field(title='JID')
    target: TaskJobTarget = Field(title='Job salt target')
    status: TaskJobStatus = Field(title='Job status', default=TaskJobStatus.pending)
    returns_statuses: dict[str, TaskJobReturnStatus] = Field(title='Job returns statuses by minions', default={})

    minions_by_targeting: list[str] = Field(title='List of minions ids by targeting')
    minions_from_salt: list[str] | None = Field(title='Computed minions by salt', default=None)

    created_dt: Iso8601ZDatetime = Field(title='Created stamp', default_factory=utc_now)
    finished_dt: Iso8601ZDatetime | None = Field(title='Finished stamp', default=None)


class TaskTargetMinion(BaseModel):
    minion_id: str
    master: str


class TaskTemplateShort(BaseModel):
    id: str
    title: str
    name: str
    repo_id: str
    commit_hash: str


class CollectionShort(BaseModel):
    id: str
    slug: str
    title: str


class TaskMinionStatus(str, Enum):
    pending = 'pending'
    in_work = 'in_work'
    success = 'success'
    failed = 'failed'


class TaskMinionJobStatus(str, Enum):
    created = 'created'
    in_work = 'in_work'
    success = 'success'
    failed = 'failed'
    ignored = 'ignored'


class TaskMinion(BaseModel):
    id: str | None = Field(title='Minion id', default=None)
    minion_id: str
    master: str

    status: TaskMinionStatus = Field(title='status', default=TaskMinionStatus.pending)

    jobs: dict[str, TaskMinionJobStatus] = Field(title='Jobs', default={})

    start_last_dt: Iso8601ZDatetime | None = Field(title='Last job start dt', default=None)
    finished_dt: Iso8601ZDatetime | None = Field(title='Processing finished dt', default=None)

    @computed_field(title='Count job runs')
    def count_runs(self) -> int:
        return len(self.jobs)


class TaskPostProcessingType(str, Enum):
    on_success = 'on_success'
    on_anyway = 'on_anyway'


class TaskPostProcessingMinionForWait(BaseModel):
    minion_id: str = Field(title='Minion ID')
    master: str = Field(title='Master')


class TaskPostProcessingCreate(BaseModel):
    type: TaskPostProcessingType = Field(title='Postprocessing type')

    wait_minions: list[TaskPostProcessingMinionForWait] = Field(title='Wait minions', default=[])
    wait_minions_ttl: int = Field(title='Wait minions TTL', ge=1, default=60 * 5)

    task_create_request: 'TaskCreateRequestSchema | None' = Field(title='Create task', default=None)

    notify: bool = Field(title='Notify', default=False)


class TaskCreateRequestSchema(BaseModel):
    task_template_id: str | None = Field(title='Task template id', default=None)
    fun: str | None = Field(title='Salt fun', default=None)

    salt_masters: list[str] = ['salt-master']
    data: TaskData | None = None

    collection_id: str = Field(title='Collection id')
    query: dict = Field(title='Query', default={})
    minions: list[TaskTargetMinion] = Field(title='Minions', default=[])

    batch_size: int | None = Field(title='Batch size', default=None)
    max_jobs_count_at_same_time: int = Field(title='Max jobs count at some time', ge=1, default=1)
    max_retries: int = Field(title='Max retries', default=3)

    postprocessing: TaskPostProcessingCreate | None = Field(title='Postprocessing', default=None)

    @model_validator(mode='after')
    def validate_local_path(self) -> Self:
        if self.task_template_id is None and self.fun is None:
            msg = 'One of `task_template` or `fun` must be set'
            raise ValueError(msg)

        if self.task_template_id is not None and self.fun is not None:
            msg = 'Only one of `task_template` or `fun` can be set'
            raise ValueError(msg)

        return self


class TaskPostProcessing(TaskPostProcessingCreate):
    task_create_id: str | None = Field(title='Task ID', default=None)
    notify_dt: Iso8601ZDatetime | None = Field(title='Notify dt', default=None)


class TaskStatus(StrEnum):
    created = 'created'
    running = 'running'
    stopping = 'stopping'
    stopped = 'stopped'
    postprocessing = 'postprocessing'
    finished = 'finished'


class TaskModel(BaseModel):
    id: str = Field(title='ID', alias='_id', serialization_alias='id')
    jobs: dict[str, TaskJob] = Field(title='Jobs', default={})
    minions: dict[str, TaskMinion] = Field(title='Minions failed', default={})
    status: TaskStatus = Field(title='Status', default=TaskStatus.created)

    run_dt: Iso8601ZDatetime | None = Field(title='Run datetime', default=None)
    stopped_dt: Iso8601ZDatetime | None = Field(title='Stopped datetime', default=None)
    postprocessing_dt: Iso8601ZDatetime | None = Field(title='Postprocessing datetime', default=None)
    finished_dt: Iso8601ZDatetime | None = Field(title='Finished datetime', default=None)

    postprocessing: TaskPostProcessing | None = Field(title='Postprocessing', default=None)

    parent_task_id: str | None = Field(title='Parent task id', default=None)
    task_template: TaskTemplateShort | None = Field(title='Task template', default=None)

    fun: str = Field(title='Salt fun')
    task_args: list[str] | None = Field(title='Args', default=None)
    task_kwargs: dict[str, Any] | None = Field(title='Kwargs', default=None)

    target_collection: CollectionShort = Field(title='Target collection')
    target_query: dict[str, Any] = Field(title='Target query', default={})
    target_minions: list[TaskTargetMinion] = Field(title='Target minions', default=[])
    target_masters: list[str] = Field(title='Target masters', default=[])

    batch_size: int | None = Field(title='Batch size', default=None)
    max_jobs_count_at_same_time: int = Field(title='Max jobs count at some time', ge=1, default=1)
    max_retries: int = Field(title='Max retries', ge=1, default=3)

    user: UserShort
    source: TaskSource | None = Field(title='Source', default=None)

    created: Iso8601ZDatetime = Field(title='Created')
    modified: Iso8601ZDatetime = Field(title='Modified')

    @computed_field(title='Total minions')
    def total_minions(self) -> int:
        return len(self.minions)

    @computed_field(title='Minions count by status')
    def minions_count_by_status(self) -> dict[TaskMinionStatus, int]:
        result: dict[TaskMinionStatus, int] = dict.fromkeys(TaskMinionStatus, 0)

        for minion in self.minions.values():
            result[minion.status] += 1

        return result
