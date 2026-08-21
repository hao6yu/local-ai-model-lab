import type { ChatErrorPayload, ReasoningEffort } from "./chat";

export type EvalState = "created" | "running" | "completed" | "failed";

export const EVAL_STATES: EvalState[] = ["created", "running", "completed", "failed"];

export interface EvalScore {
  accuracy: number | null;
  completeness: number | null;
  instruction_following: number | null;
  appropriate_judgment: number | null;
  refusal: boolean;
  hallucination: boolean;
  truncation: boolean;
  unsafe_output: boolean;
  format_failure: boolean;
  note: string | null;
}

export const EMPTY_SCORE: EvalScore = {
  accuracy: null,
  completeness: null,
  instruction_following: null,
  appropriate_judgment: null,
  refusal: false,
  hallucination: false,
  truncation: false,
  unsafe_output: false,
  format_failure: false,
  note: null,
};

export interface EvalMetrics {
  ttft_seconds: number | null;
  completion_seconds: number | null;
  generation_tps: number | null;
  generation_tps_source: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  token_source: string | null;
  request_started_at: number | null;
}

export interface EvalError {
  code: string;
  message: string;
}

export type InputType = "text" | "image";
export type CaseType = "transcribe" | "interpret" | "image" | null;

export interface EvalResult {
  id: number;
  case_id: string;
  index: number;
  category: string | null;
  prompt: string;
  response: string | null;
  finish_reason: string | null;
  error: EvalError | null;
  metrics: EvalMetrics | null;
  state: EvalState;
  input_type: InputType | null;
  case_type: CaseType;
  image_media_type: string | null;
  image_source: "attachment" | "fixture" | null;
  scores: EvalScore | null;
}

export interface SuiteCase {
  id: string;
  category: string | null;
  prompt: string;
  input_type: InputType;
  case_type: CaseType | null;
  disabled: boolean;
}

export interface EvalRun {
  id: number;
  suite_name: string;
  suite_version: string;
  suite_hash: string;
  profile_label: string;
  model_id: string | null;
  modality: string;
  state: EvalState;
  created_at: string;
  completed_at: string | null;
  completed_cases: number;
  total_cases: number;
  reasoning_effort: ReasoningEffort;
  temperature: number | null;
  max_tokens: number | null;
  context_window: number | null;
  notes: string | null;
  suite_snapshot: string | null;
  results: EvalResult[];
}

export interface SuiteListItem {
  name: string;
  version: string;
  hash: string;
  case_count: number;
  source_path: string;
}

export interface EvalRunBrief {
  id: number;
  suite_name: string;
  suite_version: string;
  state: EvalState;
  created_at: string;
  completed_at: string | null;
  completed_cases: number;
  total_cases: number;
}

export interface EvalScoreSummary {
  mean_score: number | null;
  scored_count: number;
  total_count: number;
}

export interface EvalSideSummaries {
  overall: EvalScoreSummary | null;
  by_category: Record<string, EvalScoreSummary>;
}

export interface EvalComparison {
  left: EvalRun;
  right: EvalRun;
  summaries: {
    left: EvalSideSummaries;
    right: EvalSideSummaries;
  };
}

export interface EvalProgressPayload {
  run_id: number;
  case_index: number;
  total: number;
  case_id: string;
  status: EvalState;
}

export interface EvalResultEventPayload {
  run_id: number;
  case_index: number;
  total: number;
  case_id: string;
  state: EvalState;
  response: string | null;
  finish_reason: string | null;
  error: EvalError | null;
  metrics: EvalMetrics | null;
}

export interface EvalRunDonePayload {
  run_id: number;
  state: EvalState;
}

export interface EvaluateStreamRequest {
  run_id: number;
}

export interface EvaluationRunRequest {
  suite_name: string;
  suite_version: string;
  reasoning_effort: ReasoningEffort;
  temperature: number | null;
  max_tokens: number | null;
  profile_label: string | null;
  model_id: string | null;
  context_window: number | null;
  modality: string;
  notes: string | null;
  images: EvalImageAttachment[];
}

export interface EvalImageAttachment {
  case_id: string;
  data_url: string;
}

export type EvaluateEvent =
  | { kind: "progress"; payload: EvalProgressPayload }
  | { kind: "result"; payload: EvalResultEventPayload }
  | { kind: "done"; payload: EvalRunDonePayload }
  | { kind: "error"; payload: ChatErrorPayload };

export interface EvaluateCallbacks {
  onProgress(payload: EvalProgressPayload): void;
  onResult(payload: EvalResultEventPayload): void;
  onDone(payload: EvalRunDonePayload): void;
  onError(payload: ChatErrorPayload): void;
  onAborted(): void;
}
