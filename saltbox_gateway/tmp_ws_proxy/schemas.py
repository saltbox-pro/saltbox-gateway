from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, TypeVar

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
from saltbox_gateway.tmp_ws_proxy.utils import JID, fill_salt_kwarg_from_arg
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
