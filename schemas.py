from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AliasPath, BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    role: Literal["agent", "admin"]
    is_active: bool
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class CitationOut(BaseModel):
    chunk_id: str
    source_id: str
    source_type: str
    title: str
    page: int | None = None
    section: str = ""
    url: str = ""
    score: float = 0.0
    snippet: str = ""


class ToolEventOut(BaseModel):
    name: str
    status: str
    latency_ms: int = 0
    output_summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=10000)
    domain: str = "tech_support"
    top_k: int = Field(default=5, ge=1, le=20)
    conversation_id: str | None = None
    code: str | None = None


class QueryResult(BaseModel):
    trace_id: str
    route: str
    answer: str
    abstained: bool
    confidence: float
    citations: list[CitationOut] = Field(default_factory=list)
    tool_events: list[ToolEventOut] = Field(default_factory=list)
    model: str | None = None
    token_usage: dict[str, int] = Field(default_factory=dict)
    cost_usd: float = 0.0
    latency_ms: int = 0
    escalation: dict[str, Any] | None = None


class ConversationCreate(BaseModel):
    title: str = "New support conversation"
    domain: str = "tech_support"


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    status: str
    domain: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    trace_id: str | None
    citations: list[dict[str, Any]]
    tool_events: list[dict[str, Any]]
    model: str | None
    token_usage: dict[str, Any]
    latency_ms: int | None
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut] = Field(default_factory=list)


class TicketCreate(BaseModel):
    conversation_id: str | None = None
    title: str
    summary: str
    attempted_steps: list[str] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    recommendation: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class TicketUpdate(BaseModel):
    status: Literal["draft", "queued", "in_progress", "resolved", "closed"] | None = None
    assignee_id: str | None = None
    recommendation: str | None = None


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str | None
    created_by: str
    assignee_id: str | None
    status: str
    title: str
    summary: str
    attempted_steps: list[str]
    citations: list[dict[str, Any]]
    recommendation: str
    metadata: dict[str, Any] = Field(validation_alias=AliasPath("extra_metadata"))
    created_at: datetime
    updated_at: datetime


class UserUpdate(BaseModel):
    role: Literal["agent", "admin"] | None = None
    is_active: bool | None = None


class SourceCreate(BaseModel):
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    name: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_key: str
    kind: str
    repository: str | None
    name: str
    config: dict[str, Any]
    status: str
    last_synced_at: datetime | None
    created_at: datetime


class EvaluationRunCreate(BaseModel):
    domain: str = "tech_support"
    version_label: str = "manual"
    gold_path: str | None = None


class EvaluationRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_by: str | None
    version_label: str
    domain: str
    status: str
    metrics: dict[str, Any]
    comparison: dict[str, Any]
    report_object_key: str | None
    created_at: datetime
    finished_at: datetime | None


class GoldCaseCreate(BaseModel):
    case_key: str = Field(min_length=1, max_length=128)
    domain: str = "tech_support"
    query: str = Field(min_length=1, max_length=10000)
    expected_source_id: str = ""
    expected_answer_contains: list[str] = Field(default_factory=list)
    should_abstain: bool = False
    notes: str = ""


class GoldCaseUpdate(BaseModel):
    status: Literal["draft", "approved", "rejected"] | None = None
    notes: str | None = None
    expected_source_id: str | None = None
    expected_answer_contains: list[str] | None = None


class GoldCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_key: str
    domain: str
    query: str
    expected_source_id: str
    expected_answer_contains: list[str]
    should_abstain: bool
    status: str
    notes: str
    reviewed_by: str | None
    created_at: datetime
    updated_at: datetime


class TraceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str | None
    conversation_id: str | None
    route: str
    status: str
    model: str | None
    latency_ms: int | None
    cost_usd: float
    events: list[dict[str, Any]]
    metadata: dict[str, Any] = Field(validation_alias=AliasPath("extra_metadata"))
    created_at: datetime

