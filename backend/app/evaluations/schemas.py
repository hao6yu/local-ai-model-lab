from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.chat import ReasoningEffort

RunState = str
ResultState = str


class EvalMetricsPayload(BaseModel):
    ttft_seconds: float | None = None
    completion_seconds: float | None = None
    generation_tps: float | None = None
    generation_tps_source: "str | None" = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    token_source: "str | None" = None
    request_started_at: float | None = None


class EvalErrorPayload(BaseModel):
    code: str
    message: str


class EvalResultPayload(BaseModel):
    case_id: str
    category: str | None = None
    prompt: str
    response: str | None = None
    finish_reason: str | None = None
    error: EvalErrorPayload | None = None
    metrics: EvalMetricsPayload | None = None
    state: ResultState = "in_progress"


class EvaluationRunRequest(BaseModel):
    suite_name: str = Field(min_length=1, max_length=200)
    suite_version: str = Field(min_length=1, max_length=50)
    reasoning_effort: ReasoningEffort = "off"
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    profile_label: str | None = Field(default=None, min_length=1, max_length=300)
    model_id: str | None = Field(default=None, max_length=200)
    context_window: int | None = Field(default=None, ge=1)
    modality: str = Field(default="text", min_length=1, max_length=50)
    notes: str | None = Field(default=None, max_length=2000)


class SuiteListItem(BaseModel):
    name: str
    version: str
    hash: str
    case_count: int
    source_path: str


class EvalRunSummary(BaseModel):
    id: int
    suite_name: str
    suite_version: str
    suite_hash: str
    profile_label: str
    model_id: str | None = None
    modality: str = "text"
    state: RunState = "created"
    created_at: datetime
    completed_at: datetime | None = None
    completed_cases: int = 0
    total_cases: int = 0


class EvalScorePayload(BaseModel):
    accuracy: int | None = Field(default=None, ge=0, le=2)
    completeness: int | None = Field(default=None, ge=0, le=2)
    instruction_following: int | None = Field(default=None, ge=0, le=2)
    appropriate_judgment: int | None = Field(default=None, ge=0, le=2)
    refusal: bool = False
    hallucination: bool = False
    truncation: bool = False
    unsafe_output: bool = False
    failed: bool = False
    note: str | None = Field(default=None, max_length=2000)


class EvalResultSummary(BaseModel):
    id: int
    case_id: str
    index: int
    category: str | None = None
    prompt: str
    response: str | None = None
    finish_reason: str | None = None
    error: EvalErrorPayload | None = None
    metrics: EvalMetricsPayload | None = None
    state: ResultState = "in_progress"


class EvalResultWithScores(EvalResultSummary):
    scores: EvalScorePayload | None = None


class EvalRunDetail(EvalRunSummary):
    reasoning_effort: ReasoningEffort = "off"
    temperature: float | None = None
    max_tokens: int | None = None
    context_window: int | None = None
    notes: str | None = None
    results: list[EvalResultWithScores] = []


class EvalProgressPayload(BaseModel):
    run_id: int
    case_index: int
    total: int
    case_id: str
    status: ResultState = "in_progress"


class EvalResultEvent(BaseModel):
    run_id: int
    case_index: int
    total: int
    case_id: str
    state: ResultState = "completed"
    response: str | None = None
    finish_reason: str | None = None
    error: EvalErrorPayload | None = None
    metrics: EvalMetricsPayload | None = None


class EvalRunDonePayload(BaseModel):
    run_id: int
    state: RunState


class ManualScoreUpdate(BaseModel):
    accuracy: int | None = Field(default=None, ge=0, le=2)
    completeness: int | None = Field(default=None, ge=0, le=2)
    instruction_following: int | None = Field(default=None, ge=0, le=2)
    appropriate_judgment: int | None = Field(default=None, ge=0, le=2)
    refusal: bool = False
    hallucination: bool = False
    truncation: bool = False
    unsafe_output: bool = False
    failed: bool = False
    note: str | None = Field(default=None, max_length=2000)
