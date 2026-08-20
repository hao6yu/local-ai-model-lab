export type ChatRole = "system" | "user" | "assistant";

export type ReasoningEffort = "off" | "low" | "medium" | "high" | "xhigh";

export type ChatErrorCode =
  | "not_configured"
  | "upstream_timeout"
  | "disconnected"
  | "upstream_error"
  | "context_limit"
  | "malformed_stream"
  | "stream_error";

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

export interface ChatUsage {
  prompt_tokens: number | null;
  completion_tokens: number | null;
}

export interface ChatMetrics {
  ttft_seconds: number | null;
  completion_seconds: number;
  generation_tps: number | null;
  token_source: "upstream" | null;
}

export interface ChatChunkPayload {
  content: string;
}

export interface ChatDonePayload {
  usage: ChatUsage | null;
  finish_reason: string | null;
  metrics: ChatMetrics;
}

export interface ChatErrorPayload {
  code: ChatErrorCode;
  message: string;
}

export interface ChatStreamRequest {
  model_profile: string | null;
  messages: ChatMessage[];
  temperature: number | null;
  max_tokens: number | null;
  reasoning_effort: ReasoningEffort;
}
