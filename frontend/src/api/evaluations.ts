import type { ChatErrorPayload } from "../types/chat";
import {
  describeHttpError,
  getJson,
  patchJson,
  postJson,
} from "./client";
import type {
  EvaluationRunRequest,
  EvaluateCallbacks,
  EvaluateEvent,
  EvalComparison,
  EvalProgressPayload,
  EvalRunDonePayload,
  EvalResultEventPayload,
  EvalRun,
  EvalScore,
  EvalRunBrief,
  SuiteCase,
  SuiteListItem,
} from "../types/evaluations";

export function getSuites(): Promise<SuiteListItem[]> {
  return getJson<SuiteListItem[]>("/api/suites");
}

export function getSuiteCases(name: string): Promise<SuiteCase[]> {
  return getJson<SuiteCase[]>(`/api/suites/${encodeURIComponent(name)}/cases`);
}

export function getEvaluationRun(id: number): Promise<EvalRun> {
  return getJson<EvalRun>(`/api/evaluation-runs/${id}`);
}

export function updateResultScore(id: number, score: EvalScore): Promise<EvalScore> {
  return patchJson<EvalScore, EvalScore>(`/api/results/${id}/score`, score);
}

export async function createEvaluationRun(request: EvaluationRunRequest): Promise<number> {
  const { id } = await postJson<EvaluationRunRequest, { id: number }>(
    "/api/evaluation-runs",
    request,
  );
  return id;
}

export async function getEvaluationImage(
  runId: number,
  resultId: number,
): Promise<string> {
  const response = await fetch(
    `/api/evaluation-runs/${runId}/results/${resultId}/image`,
  );
  if (!response.ok) {
    throw new Error(`requesting result image failed with HTTP ${response.status}`);
  }
  const mediaType = response.headers.get("Content-Type") ?? "image/jpeg";
  const buffer = await response.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let base64 = "";
  for (let i = 0; i < bytes.length; i += 8192) {
    base64 += String.fromCharCode.apply(null, [...bytes.subarray(i, i + 8192)]);
  }
  return `data:${mediaType};base64,${base64}`;
}

export function listSavedRuns(): Promise<EvalRunBrief[]> {
  return getJson<EvalRunBrief[]>("/api/evaluation-runs");
}

export async function getComparison(left: number, right: number): Promise<EvalComparison> {
  const response = await fetch(`/api/comparisons?left=${left}&right=${right}`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(await describeHttpError(response));
  }
  return (await response.json()) as EvalComparison;
}

export async function getComparisonExport(
  left: number,
  right: number,
  format: "markdown" | "json",
): Promise<string> {
  const response = await fetch(`/api/comparisons/export?left=${left}&right=${right}&format=${format}`, {
    headers: { Accept: format === "markdown" ? "text/markdown" : "application/json" },
  });
  if (!response.ok) {
    const detail = await describeHttpError(response);
    throw new Error(
      `exporting comparison with ${format} failed with HTTP ${response.status} — ${detail}`,
    );
  }
  return response.text();
}

export async function evaluateSuite(
  runId: number,
  callbacks: EvaluateCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`/api/evaluation-runs/${runId}/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal,
    });
  } catch (error) {
    if (isAborted(error, signal)) {
      callbacks.onAborted();
      return;
    }
    callbacks.onError({
      code: "upstream_error",
      message: "The request to the model endpoint failed.",
    });
    return;
  }

  if (!response.ok) {
    callbacks.onError({
      code: "upstream_error",
      message: await describeHttpError(response),
    });
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    callbacks.onError({
      code: "malformed_stream",
      message: "The model endpoint returned a response without a stream.",
    });
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";
  let event = "";
  let hasEvent = false;
  let data = "";
  let settled = false;

  const dispatch = () => {
    if (!hasEvent || settled) return;
    try {
      const payload = JSON.parse(data);
      const mapped = mapEvent(event, payload) as EvaluateEvent;
      if (mapped.kind === "progress") callbacks.onProgress(mapped.payload);
      else if (mapped.kind === "result") callbacks.onResult(mapped.payload);
      else if (mapped.kind === "done") {
        settled = true;
        callbacks.onDone(mapped.payload);
      } else if (mapped.kind === "error") {
        settled = true;
        callbacks.onError(mapped.payload as ChatErrorPayload);
      }
    } catch {
      settled = true;
      callbacks.onError({
        code: "malformed_stream",
        message: "The model endpoint sent a malformed stream payload.",
      });
    }
    event = "";
    hasEvent = false;
    data = "";
  };

  const interrupt = (message: string) => {
    if (settled) return;
    settled = true;
    callbacks.onError({ code: "stream_error", message });
  };

  try {
    while (true) {
      if (signal?.aborted) {
        settled = true;
        callbacks.onAborted();
        return;
      }
      let result: ReadableStreamReadResult<Uint8Array>;
      try {
        result = await reader.read();
      } catch (error) {
        if (isAborted(error, signal)) {
          settled = true;
          callbacks.onAborted();
          return;
        }
        interrupt("The model stream was interrupted before completing.");
        return;
      }
      if (result.done) break;
      buffer += decoder.decode(result.value, { stream: true });

      let newlineIndex = -1;
      while ((newlineIndex = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, newlineIndex);
        buffer = buffer.slice(newlineIndex + 1);
        if (line === "") {
          dispatch();
        } else if (line.startsWith("event:")) {
          event = line.slice(6).trim();
          hasEvent = true;
        } else if (line.startsWith("data:")) {
          data = line.slice(5).trim();
        }
      }
    }
  } finally {
    reader.releaseLock();
  }

  dispatch();

  if (signal?.aborted) {
    settled = true;
    callbacks.onAborted();
    return;
  }

  if (!settled) {
    interrupt("The model stream was interrupted before completing.");
  }
}

function isAborted(error: unknown, signal?: AbortSignal): boolean {
  if (signal?.aborted) return true;
  return (error as { name?: string } | null)?.name === "AbortError";
}

function mapEvent(event: string, payload: unknown): EvaluateEvent {
  switch (event) {
    case "progress":
      return { kind: "progress", payload: payload as EvalProgressPayload };
    case "result":
      return { kind: "result", payload: payload as EvalResultEventPayload };
    case "done":
      return { kind: "done", payload: payload as EvalRunDonePayload };
    default:
      return { kind: "error", payload } as unknown as EvaluateEvent;
  }
}
