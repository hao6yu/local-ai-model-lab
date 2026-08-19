import type { HealthResponse, RuntimeResponse } from "../types/health";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`requesting ${path} failed with HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export function getHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>("/api/health");
}

export function getRuntime(): Promise<RuntimeResponse> {
  return getJson<RuntimeResponse>("/api/runtime");
}
