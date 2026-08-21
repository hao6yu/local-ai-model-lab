export interface UpstreamHealth {
  state: "reachable" | "unavailable";
  detail: string | null;
}

export interface ProfileHealth {
  key: string;
  state: "reachable" | "unavailable";
  detail: string | null;
}

export interface HealthResponse {
  portal: "ok";
  model: UpstreamHealth;
  models: ProfileHealth[];
}

export interface RuntimeResponse {
  model_id: string | null;
  profile_label: string | null;
  context_window: number | null;
  experimental: boolean;
  default_reasoning_effort: string | null;
  default_max_tokens: number | null;
  default_model_profile: string | null;
  models: RuntimeModel[];
}

export interface RuntimeModel {
  key: string;
  model_id: string | null;
  profile_label: string | null;
  context_window: number | null;
  experimental: boolean;
  default_reasoning_effort: string | null;
  default_max_tokens: number | null;
  supports_vision: boolean;
}
