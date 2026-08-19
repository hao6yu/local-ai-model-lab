export interface UpstreamHealth {
  state: "reachable" | "unavailable";
  detail: string | null;
}

export interface HealthResponse {
  portal: "ok";
  model: UpstreamHealth;
}

export interface RuntimeResponse {
  model_id: string | null;
  profile_label: string | null;
  context_window: number | null;
  experimental: boolean;
}
