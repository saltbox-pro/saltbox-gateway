from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, TypeVar

from pydantic import AfterValidator, BaseModel, Field, PastDatetime, PlainSerializer, computed_field

from saltbox_gateway.tmp_ws_proxy.errors import JidError
from saltbox_gateway.tmp_ws_proxy.utils import JID
from saltbox_sdk.db.mongo.schemas_base import IDMixin, PyObjectId
from saltbox_sdk.db.schemas_base import SYSTEM_SHORT_USER, CreatedModifiedMixin, Source, UserShort
from saltbox_sdk.utilities.helpers import Iso8601ZDatetime as TimezoneAwareDatetime
from saltbox_sdk.utilities.helpers import format_iso8601_z, make_aware, utc_now

# Jobs

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
    starting = 'starting'
    running = 'running'
    finished = 'finished'
    launch_error = 'launch_error'


class JobReadOnlyFieldsMixin:
    tgt: str | list[str]
    tgt_type: str
    salt_master: str
    fun: str
    arg: list | None = None
    kwarg: dict | None = None

    user: UserShort | None = Field(default=SYSTEM_SHORT_USER)
    source: Source | None = None


class JobEditableFieldsMixin:
    system_user: str | None = None
    minions: list[str] = Field(default=[])
    missing: list[str] = Field(default=[])
    stamp: TimezoneAwareDatetime | None = Field(default=None)
    status: JobStatus = Field(default=JobStatus.starting)
    error_type: str | None = None


class JobComputedFieldsMixin:
    @computed_field(title='Timestamp decoded from JID')
    def fms_jid_timestamp(self) -> Annotated[datetime, PastDatetime]:
        return JID(self.jid).to_datetime()  # type: ignore


class JobAggregateFieldsMixin:
    returning: dict[str, bool | None] = Field(default={})


class JobModel(
    BaseModel,
    CreatedModifiedMixin,
    JobReadOnlyFieldsMixin,
    JobEditableFieldsMixin,
    JobComputedFieldsMixin,
    JobAggregateFieldsMixin,
    IDMixin,
):
    jid: StrJid


class JobSimpleSchema(BaseModel, IDMixin):
    jid: StrJid
    salt_master: str
    status: JobStatus


# JobReturn schemas


class JobReturnStatus(StrEnum):
    waiting = 'waiting'
    success = 'success'
    failed = 'failed'
    timeout = 'timeout'


class JobReturnReadOnlyFieldsMixin:
    minion_id: str
    salt_master: str
    jid: StrJid
    fun: str
    user: UserShort | None = Field(default=SYSTEM_SHORT_USER)
    source: Source | None = None


class JobReturnEditableFieldsMixin:
    status: JobReturnStatus = Field(default=JobReturnStatus.waiting)
    retcode: int | None = None
    fun_args: list | None = None
    fun_kwarg: dict | None = None
    system_user: str | None = None
    stamp: TimezoneAwareDatetime | None = None
    stamp_job: TimezoneAwareDatetime | None = Field(default=None)


class JobReturnAggregatedFieldsMixin:
    success: bool | None = None


class JobReturnModel(
    BaseModel,
    JobReturnAggregatedFieldsMixin,
    CreatedModifiedMixin,
    JobReturnReadOnlyFieldsMixin,
    JobReturnEditableFieldsMixin,
    IDMixin,
):
    data: Any = Field(default=None)


# Task-related schemas


class TaskType(StrEnum):
    classic = 'classic'
    policy = 'policy'


class TaskStatus(StrEnum):
    created = 'created'
    wait_minions = 'wait_minions'
    running = 'running'
    stopping = 'stopping'
    stopped = 'stopped'
    finished = 'finished'


class TaskTemplateShort(BaseModel, IDMixin):
    id: PyObjectId = Field(title='ID', serialization_alias='id')
    title: str = Field(title='Template title')
    name: str = Field(title='Template name')
    repo_id: PyObjectId = Field(title='Repository id')
    commit_hash: str = Field(title='Repository commit hash')


class CollectionShort(BaseModel):
    id: PyObjectId = Field(title='ID', serialization_alias='id')
    slug: str = Field(title='Collection slug')
    title: str = Field(title='Collection title')


class TaskStatusShort(BaseModel, CreatedModifiedMixin):
    type: TaskStatus = Field(title='Status')
    data: dict = Field(title='Status data', default_factory=dict)


class TaskReadOnlyFieldsMixin:
    task_type: TaskType = Field(title='Task type')

    target_collection_id: PyObjectId = Field(title='Target ID')
    target_query: dict[str, Any] = Field(title='Target query', default={})

    task_template_id: PyObjectId | None = Field(title='Task template id', default=None)

    fun: str = Field(title='Salt fun')
    arg: list[str] | None = Field(title='Arg', default=None)
    kwarg: dict[str, Any] | None = Field(title='Kwarg', default=None)

    user: UserShort
    source: Source | None = Field(title='Source', default=None)


class TaskEditableFieldsMixin:
    batch_size: int = Field(title='Batch size', ge=0, default=0)
    max_jobs_count_at_same_time: int = Field(title='Max jobs count at some time', ge=1, default=1)

    max_retries: int = Field(title='Max retries', ge=0, default=1)
    retry_delay: int = Field(title='Retry delay', description='in seconds', ge=0, default=10)

    last_sync_dt: TimezoneAwareDatetime | None = Field(title='Last sync datetime', default=None)


class TaskTemplateJoinedFieldsMixin:
    task_template: TaskTemplateShort | None = Field(title='Task template', default=None)


class TaskTargetCollectionJoinedFieldsMixin:
    target_collection: CollectionShort = Field(title='Target collection')


class TaskStatusJoinedFieldsMixin:
    status: TaskStatusShort = Field(
        title='Status', default=TaskStatusShort(type=TaskStatus.created, created=utc_now(), modified=utc_now())
    )


class TaskJobJoinedFieldsMixin[TaskJobJoinedSchema: BaseModel]:
    jobs: list[TaskJobJoinedSchema] = Field(title='Jobs', default=[])


class TaskMinionsCountAggregation(BaseModel):
    total: int = Field(title='Total number of minions', default=0)
    pending: int = Field(title='Pending minions', default=0)
    busy: int = Field(title='Busy', default=0)
    in_work: int = Field(title='In work', default=0)
    success: int = Field(title='Success', default=0)
    failed: int = Field(title='Failed', default=0)


class TaskAggregatedFieldsMixin:
    minions_count: TaskMinionsCountAggregation = Field()


class TaskComputedFieldsMixin: ...


class TaskModel(
    BaseModel,
    CreatedModifiedMixin,
    TaskTemplateJoinedFieldsMixin,
    TaskTargetCollectionJoinedFieldsMixin,
    TaskStatusJoinedFieldsMixin,
    TaskAggregatedFieldsMixin,
    TaskEditableFieldsMixin,
    TaskReadOnlyFieldsMixin,
    TaskComputedFieldsMixin,
    IDMixin,
): ...


# Task minion


class TaskMinionStatus(StrEnum):
    pending = 'pending'
    busy = 'busy'
    in_work = 'in_work'
    success = 'success'
    failed = 'failed'


class TaskMinionJobStatus(StrEnum):
    created = 'created'
    in_work = 'in_work'
    success = 'success'
    failed = 'failed'
    ignored = 'ignored'


class TaskMinionReadOnlyFieldsMixin:
    task_id: PyObjectId = Field(title='Task ID')
    minion_inner_id: PyObjectId = Field(title='Minion Mongo ID')


class TaskMinionEditableFieldsMixin:
    status: TaskMinionStatus = Field(title='Status', default=TaskMinionStatus.pending)

    jobs: dict[str, TaskMinionJobStatus] = Field(title='Jobs', default={})

    start_last_dt: TimezoneAwareDatetime | None = Field(title='Last job start dt', default=None)
    finished_dt: TimezoneAwareDatetime | None = Field(title='Processing finished dt', default=None)


class TaskMinionJoinedFieldsMixin:
    minion_id: str = Field(title='Minion ID')
    master: str = Field(title='Master')
    last_activity: TimezoneAwareDatetime | None = Field(title='Last activity', default=None)


class TaskMinionModel(
    BaseModel,
    TaskMinionJoinedFieldsMixin,
    CreatedModifiedMixin,
    TaskMinionReadOnlyFieldsMixin,
    TaskMinionEditableFieldsMixin,
    IDMixin,
):
    @computed_field(title='Count job runs')
    def count_runs(self) -> int:
        return len(self.jobs)
