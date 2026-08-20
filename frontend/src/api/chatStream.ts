import type {
  ChatChunkPayload,
  ChatDonePayload,
  ChatErrorPayload,
  ChatStreamRequest,
} from "../types/chat";

export interface ChatStreamCallbacks {
  onChunk(content: string): void;
  onDone(payload: ChatDonePayload): void;
  onError(payload: ChatErrorPayload): void;
  onAborted(): void;
}

const STREAM_INTERRUPTED = "The model stream was interrupted before completing.";

function isAborted(error: unknown, signal?: AbortSignal): boolean {
  if (signal?.aborted) {
    return true;
  }
  return (error as { name?: string } | null)?.name === "AbortError";
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

export async function streamChat(
  request: ChatStreamRequest,
  callbacks: ChatStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
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
    if (!hasEvent) {
      return;
    }
    if (settled) {
      return;
    }
    try {
      if (event === "chunk") {
        callbacks.onChunk((JSON.parse(data) as ChatChunkPayload).content);
      } else if (event === "done") {
        settled = true;
        callbacks.onDone(JSON.parse(data) as ChatDonePayload);
      } else if (event === "error") {
        settled = true;
        callbacks.onError(JSON.parse(data) as ChatErrorPayload);
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
    if (settled) {
      return;
    }
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
        interrupt(STREAM_INTERRUPTED);
        return;
      }
      if (result.done) {
        break;
      }
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
    interrupt(STREAM_INTERRUPTED);
  }
}
