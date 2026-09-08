"""Business-independent model, tool and runtime ports."""
from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol
from uuid import uuid4
import asyncio

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DTO(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ModelUnavailable(Exception):
    """Transport/provider failure, distinct from repairable model output syntax."""
    def __init__(self, status=None, code=None):
        super().__init__('MODEL_REQUEST_UNAVAILABLE')
        self.status=status
        self.code=code


class Part(DTO):
    type: Literal['text', 'tool_call', 'tool_result', 'artifact']
    text: str | None = None
    call_id: str | None = None
    name: str | None = None
    arguments: dict | None = None
    result: dict | None = None
    ref: str | None = None

    @model_validator(mode='after')
    def validate_part(self):
        required={'text':('text',),'tool_call':('call_id','name','arguments'),'tool_result':('call_id','result'),'artifact':('ref',)}[self.type]
        for field_name in required:
            value=getattr(self,field_name)
            if value is None or field_name in {'call_id','name','ref'} and not value:
                raise ValueError(f'{self.type} part requires {field_name}')
        for field_name in ('text','call_id','name','arguments','result','ref'):
            if field_name not in required and getattr(self,field_name) is not None:
                raise ValueError(f'{field_name} does not belong to a {self.type} part')
        return self


class ModelMessage(DTO):
    id: str = Field(default_factory=lambda: str(uuid4()))
    role: Literal['system', 'user', 'assistant', 'tool']
    content: list[Part]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = Field(default_factory=dict)


class ModelEvent(DTO):
    type: Literal['text_delta', 'tool_call_delta', 'tool_call_ready', 'usage', 'turn_end']
    message_id: str | None = None
    text: str | None = None
    call_id: str | None = None
    name: str | None = None
    arguments_fragment: str | None = None
    arguments: dict | None = None
    usage: dict | None = None
    finish_reason: Literal['stop', 'tool_calls', 'length', 'error'] | None = None


class Capabilities(DTO):
    native_tools: bool
    streaming: bool
    context_window: int = Field(gt=2048)
    max_output: int = Field(gt=0)
    thinking_modes: list[bool] = Field(default_factory=lambda: [False])


class ToolError(DTO):
    code: str
    message: str
    fields: list[dict] = Field(default_factory=list)
    retryable: bool = False
    candidates: list[dict] = Field(default_factory=list)


class ToolResult(DTO):
    call_id: str = ''
    status: Literal['OK', 'PARTIAL', 'EMPTY', 'AMBIGUOUS', 'NOT_FOUND', 'UNAVAILABLE', 'ERROR'] = 'OK'
    data: dict = Field(default_factory=dict)
    artifact_refs: list[str] = Field(default_factory=list)
    effective_input: dict = Field(default_factory=dict)
    provenance: list[dict] = Field(default_factory=list)
    coverage: dict = Field(default_factory=lambda: {'complete': True, 'returned': 0, 'total': None, 'omissions': []})
    next_cursor: str | None = None
    error: ToolError | None = None
    cache: dict = Field(default_factory=lambda: {'hit': False, 'observed_at': None})
    metrics: dict = Field(default_factory=dict)

    @classmethod
    def failure(cls, code, message, *, status='ERROR', **details):
        return cls(status=status, error=ToolError(code=code, message=message, **details),
                   coverage={'complete':False,'returned':0,'total':None,'omissions':['operation_not_completed']})


Effect = Literal['READ', 'WORKSPACE_WRITE', 'USER_WRITE']


@dataclass
class ExecutionContext:
    workspace_id: str
    turn_id: str
    call_id: str
    server_owner: str
    deadline: float
    cancel_token: asyncio.Event
    artifact_port: Any
    authorization_port: Any
    services: dict = field(default_factory=dict)


@dataclass
class ToolDefinition:
    name: str
    description: str
    input_model: type[DTO]
    handler: Callable[[DTO, ExecutionContext], Awaitable[ToolResult]]
    effect: Effect = 'READ'
    version: str = '1'
    timeout_seconds: float = 10
    concurrency_group: str = 'default'
    operation_effects: dict[str, Effect] = field(default_factory=dict)
    progress_label: str = '读取资料'
    output_model: type[DTO] = ToolResult
    snapshot: Callable[[DTO, ExecutionContext], str] | None = None
    result_max_bytes: int = 12000
    operation_result_max_bytes: dict[str, int] = field(default_factory=dict)
    result_budget_field: str = 'operation'

    @property
    def input_schema(self):
        return self.input_model.model_json_schema()

    @property
    def output_schema(self):
        return self.output_model.model_json_schema()


class AgentModelPort(Protocol):
    def capabilities(self) -> Capabilities: ...
    def stream(self, messages: list[ModelMessage], definitions: list[ToolDefinition], limits: dict,
               cancel_token: asyncio.Event) -> AsyncIterator[ModelEvent]: ...


class SessionStore(Protocol):
    def claim_run(self, run_id: str, owner: str) -> dict: ...
    def append_message(self, run_id: str, owner: str, message: ModelMessage) -> None: ...
    def load_context_index(self, workspace_id: str) -> dict: ...
    def save_checkpoint(self, run_id: str, owner: str, **values) -> None: ...
    def finish_run(self, run_id: str, owner: str, status: str) -> None: ...


class ArtifactStore(Protocol):
    def put(self, workspace_id: str, kind: str, payload: dict, **metadata) -> str: ...
    def read(self, workspace_id: str, ref: str) -> dict: ...
    def search(self, workspace_id: str, **filters) -> dict: ...


class EventSink(Protocol):
    def append_and_publish(self, run_id: str, kind: str, payload: dict, *, owner: str | None = None) -> None: ...


@dataclass
class RuntimePorts:
    model: AgentModelPort
    sessions: SessionStore
    artifacts: ArtifactStore
    registry: Any
    events: EventSink
    clock: Callable[[], float]
