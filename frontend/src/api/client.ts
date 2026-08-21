import type { HealthResponse, RuntimeResponse } from "../types/health";

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`requesting ${path} failed with HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function postJson<T, R>(path: string, body: T): Promise<R> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`posting to ${path} failed with HTTP ${response.status}`);
  }
  const text = await response.text();
  return (text ? (JSON.parse(text) as R) : ({}) as R);
}

export async function deleteJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { method: "DELETE", headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`deleting ${path} failed with HTTP ${response.status}`);
  }
  const text = await response.text();
  return (text ? (JSON.parse(text) as T) : ({} as T));
}

export async function patchJson<T, R>(path: string, body: T): Promise<R> {
  const response = await fetch(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`patching ${path} failed with HTTP ${response.status}`);
  }
  const text = await response.text();
  return (text ? (JSON.parse(text) as R) : ({}) as R);
}

async function describeHttpError(response: Response): Promise<string> {
  const fallback = `The model endpoint rejected the request (HTTP ${response.status}).`;
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return fallback;
  }
  if (typeof payload !== "object" || payload === null) {
    return fallback;
  }
  const body = payload as { detail?: unknown; message?: string };
  const detail = body.detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { loc?: unknown; msg?: unknown };
    const loc = Array.isArray(first?.loc) ? (first.loc as string[]).join(".") : null;
    if (typeof first?.msg === "string") {
      return loc ? `${loc}: ${first.msg}` : first.msg;
    }
    return String(first?.msg ?? "");
  }
  if (typeof detail === "string") {
    return detail;
  }
  return typeof body.message === "string" ? body.message : fallback;
}

export { describeHttpError };

export function getHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>("/api/health");
}

export function getRuntime(): Promise<RuntimeResponse> {
  return getJson<RuntimeResponse>("/api/runtime");
}
