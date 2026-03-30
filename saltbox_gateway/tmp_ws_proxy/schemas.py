from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, TypeVar

from pydantic import AfterValidator, BaseModel, Field, PastDatetime, PlainSerializer, computed_field

from saltbox_gateway.tmp_ws_proxy.errors import JidError
from saltbox_gateway.tmp_ws_proxy.utils import JID
from saltbox_sdk.db.mongo.schemas_base import PyObjectId
from saltbox_sdk.db.schemas_base import SYSTEM_SHORT_USER, CreatedModifiedMixin, Source, UserShort
from saltbox_sdk.utilities.helpers import Iso8601ZDatetime as TimezoneAwareDatetime
from saltbox_sdk.utilities.helpers import format_iso8601_z, make_aware, utc_now

JOBS_MAX_TTL = 60 * 60 * 24 * 7
JOBS_DEFAULT_TTL = 60 * 60 * 24 * 7

TASKS_DEFAULTS_BATCH_SIZE = 0
TASKS_DEFAULTS_MAX_JOBS_COUNT_AT_SAME_TIME = 1
TASKS_DEFAULTS_MAX_RETRIES = 0
TASKS_DEFAULTS_RETRY_DELAY = 10


class IDMixin:
    id: PyObjectId = Field(title='ID', serialization_alias='id')


# Jobs

T = TypeVar('T')
JID_T = TypeVar('JID_T', str, int)
Iso8601ZDatetime = Annotated[
    datetime,
    AfterValidator(make_aware),
    PlainSerializer(format_iso8601_z, when_used='json'),
    'Aware datetime serializing with Z-suffix. Unaware datetime decides UTC.',
]
SaltTgtType = Literal[
    'glob', 'pcre', 'list', 'grain', 'grain_pcre', 'pillar', 'pillar_pcre', 'nodegroup', 'range', 'compound', 'ipcidr'
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
    tgt_type: SaltTgtType
    salt_master: str
    fun: str
    arg: list | None = None
    kwarg: dict | None = None

    ttl: int = Field(ge=1, le=JOBS_MAX_TTL, default=JOBS_DEFAULT_TTL)

    user: UserShort | None = Field(default=SYSTEM_SHORT_USER)
    source: Source | None = None


class JobEditableFieldsMixin:
    system_user: str | None = None
    minions: list[str] = Field(default=[])
    missing: list[str] = Field(default=[])
    stamp: TimezoneAwareDatetime | None = Field(default=None)
    status: JobStatus = Field(default=JobStatus.starting)
    launch_error_type: str | None = None


class JobComputedFieldsMixin: ...


class JobMinionsCountAggregation(BaseModel):
    total: int = Field(title='Total number of minions', default=0)
    waiting: int = Field(title='Waiting', default=0)
    success: int = Field(title='Success', default=0)
    failed: int = Field(title='Failed', default=0)
    timeout: int = Field(title='Timeout', default=0)
    ignored: int = Field(title='Ignored', default=0)


class JobAggregateFieldsMixin:
    returning: dict[str, bool | None] = Field(default={})
    minions_count: JobMinionsCountAggregation = Field()
    waiting_expires_at_dt: datetime


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
    ignored = 'ignored'


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


class TaskTemplateDefaultsSchema(BaseModel):
    batch_size: int | None = Field(title='Batch size', ge=0, default=None)
    max_jobs_count_at_same_time: int | None = Field(title='Max jobs count at some time', ge=1, default=None)
    max_retries: int | None = Field(title='Max retries', ge=0, default=None)
    retry_delay: int | None = Field(title='Retry delay', ge=0, default=None)
    ttl: int | None = Field(ge=0, le=JOBS_MAX_TTL, default=None)


class TaskTemplateShort(BaseModel, IDMixin):
    id: PyObjectId = Field(title='ID', serialization_alias='id')
    title: str = Field(title='Template title')
    name: str = Field(title='Template name')
    repo_id: PyObjectId | None = Field(title='Repository id', default=None)
    commit_hash: str | None = Field(title='Repository commit hash', default=None)
    defaults: TaskTemplateDefaultsSchema | None = Field(title='Default values', default=None)


class CollectionShort(BaseModel, IDMixin):
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
    batch_size: int = Field(title='Batch size', ge=0, default=TASKS_DEFAULTS_BATCH_SIZE)
    max_jobs_count_at_same_time: int = Field(
        title='Max jobs count at some time', ge=1, default=TASKS_DEFAULTS_MAX_JOBS_COUNT_AT_SAME_TIME
    )

    max_retries: int = Field(title='Max retries', ge=0, default=TASKS_DEFAULTS_MAX_RETRIES)
    retry_delay: int = Field(title='Retry delay', description='in seconds', ge=0, default=TASKS_DEFAULTS_RETRY_DELAY)
    ttl: int | None = Field(ge=0, le=JOBS_MAX_TTL, default=None)

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


class TaskMinionReadOnlyFieldsMixin:
    task_id: PyObjectId = Field(title='Task ID')
    minion_inner_id: PyObjectId = Field(title='Minion Mongo ID')


class TaskMinionEditableFieldsMixin:
    status: TaskMinionStatus = Field(title='Status', default=TaskMinionStatus.pending)

    start_last_dt: TimezoneAwareDatetime | None = Field(title='Last job start dt', default=None)
    finished_dt: TimezoneAwareDatetime | None = Field(title='Processing finished dt', default=None)
    check_unactive_last_job_dt: TimezoneAwareDatetime | None = Field(title='Last check unactive dt', default=None)


class TaskMinionJoinedFieldsMixin:
    minion_id: str = Field(title='Minion ID')
    master: str = Field(title='Master')
    last_activity: TimezoneAwareDatetime | None = Field(title='Last activity', default=None)
    jobs: dict[str, JobReturnStatus] = Field(title='Jobs', default={})
    count_runs: int = Field(title='Count runs')


class TaskMinionModel(
    BaseModel,
    TaskMinionJoinedFieldsMixin,
    CreatedModifiedMixin,
    TaskMinionReadOnlyFieldsMixin,
    TaskMinionEditableFieldsMixin,
    IDMixin,
): ...
