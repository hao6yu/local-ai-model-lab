import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatStreamRequest } from "../types/chat";
import { streamChat } from "./chatStream";

const request: ChatStreamRequest = {
  model_profile: null,
  messages: [{ role: "user", content: "hi" }],
  temperature: null,
  max_tokens: null,
  reasoning_effort: "off",
};

function jsonBody(...frames: string[]): string {
  return frames.join("");
}

function event(name: string, payload: unknown): string {
  return `event: ${name}\ndata: ${JSON.stringify(payload)}\n\n`;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("streamChat", () => {
  it("parses chunk frames and the done frame", async () => {
    const collected: string[] = [];
    const finishReasons: string[] = [];
    let aborted = false;

    const body = jsonBody(
      event("chunk", { content: "Hel" }),
      event("chunk", { content: "lo" }),
      event("done", {
        usage: { prompt_tokens: 1, completion_tokens: 2 },
        finish_reason: "stop",
        metrics: {
          ttft_seconds: 0.1,
          completion_seconds: 0.3,
          generation_tps: 6.7,
          token_source: "upstream",
        },
      }),
    );

    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(body, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      ),
    );

    await streamChat(
      request,
      {
        onChunk: (content) => collected.push(content),
        onDone: (payload) => finishReasons.push(payload.finish_reason ?? ""),
        onError: () => {
          throw new Error("onError should not fire");
        },
        onAborted: () => {
          aborted = true;
        },
      },
      undefined,
    );

    expect(collected).toEqual(["Hel", "lo"]);
    expect(finishReasons).toEqual(["stop"]);
    expect(aborted).toBe(false);
  });

  it("routes an error frame to onError", async () => {
    const captured: { code: string | null; message: string | null } = { code: null, message: null };
    const body = event("error", {
      code: "context_limit",
      message: "The request exceeded the context window.",
    });

    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(body, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      ),
    );

    await streamChat(
      request,
      {
        onChunk: () => {},
        onDone: () => {
          throw new Error("onDone should not fire");
        },
        onError: (payload) => {
          captured.code = payload.code;
          captured.message = payload.message;
        },
        onAborted: () => {
          throw new Error("onAborted should not fire");
        },
      },
      undefined,
    );

    expect(captured.code).toBe("context_limit");
    expect(captured.message).toBe("The request exceeded the context window.");
  });

  it("surfaces a non-SSE validation error instead of stalling", async () => {
    const captured: { code: string | null; message: string | null } = { code: null, message: null };
    const body = JSON.stringify({
      detail: [{ loc: ["body", "max_tokens"], msg: "Input should be greater than 0" }],
    });

    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(body, {
          status: 422,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await streamChat(
      request,
      {
        onChunk: () => {
          throw new Error("onChunk should not fire");
        },
        onDone: () => {
          throw new Error("onDone should not fire");
        },
        onError: (payload) => {
          captured.code = payload.code;
          captured.message = payload.message;
        },
        onAborted: () => {
          throw new Error("onAborted should not fire");
        },
      },
      undefined,
    );

    expect(captured.code).toBe("upstream_error");
    expect(captured.message).toBe("body.max_tokens: Input should be greater than 0");
  });

  it("reports onAborted when the fetch is aborted", async () => {
    let aborted = false;
    const controller = new AbortController();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise((_resolve, reject) => {
            controller.signal.addEventListener("abort", () => {
              reject(new DOMException("Aborted", "AbortError"));
            });
          }),
      ),
    );

    const chat = streamChat(
      request,
      {
        onChunk: () => {},
        onDone: () => {
          throw new Error("onDone should not fire");
        },
        onError: () => {
          throw new Error("onError should not fire");
        },
        onAborted: () => {
          aborted = true;
        },
      },
      controller.signal,
    );
    controller.abort();
    await chat;

    expect(aborted).toBe(true);
  });

  it("reports onAborted after the first chunk when aborted mid-stream", async () => {
    const frames = ["Hel", "lo", "world"];
    let index = 0;
    let chunks = 0;
    let aborted = false;
    const controller = new AbortController();

    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (index < frames.length) {
          controller.enqueue(
            new TextEncoder().encode(
              "event: chunk\ndata: " + JSON.stringify({ content: frames[index++] }) + "\n\n",
            ),
          );
        }
      },
    });

    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(stream, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      ),
    );

    await streamChat(
      request,
      {
        onChunk: () => {
          chunks += 1;
          if (chunks === 1) {
            controller.abort();
          }
        },
        onDone: () => {
          throw new Error("onDone should not fire");
        },
        onError: () => {
          throw new Error("onError should not fire");
        },
        onAborted: () => {
          aborted = true;
        },
      },
      controller.signal,
    );

    expect(chunks).toBe(1);
    expect(aborted).toBe(true);
  });

  it("reports stream_error when a reader read failure is not an abort", async () => {
    const captured: { code: string | null; message: string | null } = { code: null, message: null };
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.error(new DOMException("stream dropped", "TypeError"));
      },
    });

    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(stream, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      ),
    );

    await streamChat(
      request,
      {
        onChunk: () => {
          throw new Error("onChunk should not fire");
        },
        onDone: () => {
          throw new Error("onDone should not fire");
        },
        onError: (payload) => {
          captured.code = payload.code;
          captured.message = payload.message;
        },
        onAborted: () => {
          throw new Error("onAborted should not fire");
        },
      },
      undefined,
    );

    expect(captured.code).toBe("stream_error");
    expect(captured.message).toBe("The model stream was interrupted before completing.");
  });

  it("reports stream_error when the stream closes without a done or error frame", async () => {
    const collected: string[] = [];
    const captured: { code: string | null; message: string | null } = { code: null, message: null };
    let phase = 0;
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (phase === 0) {
          phase = 1;
          controller.enqueue(
            new TextEncoder().encode(
              "event: chunk\ndata: " + JSON.stringify({ content: "half" }) + "\n\n",
            ),
          );
        } else {
          controller.close();
        }
      },
    });

    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(stream, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      ),
    );

    await streamChat(
      request,
      {
        onChunk: (content) => {
          collected.push(content);
        },
        onDone: () => {
          throw new Error("onDone should not fire");
        },
        onError: (payload) => {
          captured.code = payload.code;
          captured.message = payload.message;
        },
        onAborted: () => {
          throw new Error("onAborted should not fire");
        },
      },
      undefined,
    );

    expect(collected).toEqual(["half"]);
    expect(captured.code).toBe("stream_error");
    expect(captured.message).toBe("The model stream was interrupted before completing.");
  });

  it("does not emit onError when the network fails after a valid done frame", async () => {
    let phase = 0;
    let onDoneCalls = 0;
    let onErrorCalls = 0;
    let onAbortedCalls = 0;
    const doneEvent = event("done", {
      usage: { prompt_tokens: 1, completion_tokens: 2 },
      finish_reason: "stop",
      metrics: {
        ttft_seconds: 0.1,
        completion_seconds: 0.3,
        generation_tps: 5,
        token_source: "upstream",
      },
    });
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (phase === 0) {
          phase = 1;
          controller.enqueue(new TextEncoder().encode(doneEvent));
        } else if (phase === 1) {
          phase = 2;
          controller.error(new DOMException("stream dropped", "TypeError"));
        }
      },
    });

    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(stream, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      ),
    );

    await streamChat(
      request,
      {
        onChunk: () => {
          throw new Error("onChunk should not fire");
        },
        onDone: () => {
          onDoneCalls += 1;
        },
        onError: () => {
          onErrorCalls += 1;
        },
        onAborted: () => {
          onAbortedCalls += 1;
        },
      },
      undefined,
    );

    expect(onDoneCalls).toBe(1);
    expect(onErrorCalls).toBe(0);
    expect(onAbortedCalls).toBe(0);
  });

  it("ignores SSE events that arrive after the done frame", async () => {
    let onDoneCalls = 0;
    let onChunkCalls = 0;
    let onErrorCalls = 0;
    const content: string[] = [];
    const frames =
      event("done", {
        usage: { prompt_tokens: 1, completion_tokens: 2 },
        finish_reason: "stop",
        metrics: {
          ttft_seconds: 0.1,
          completion_seconds: 0.3,
          generation_tps: 5,
          token_source: "upstream",
        },
      }) +
      event("chunk", { content: "late" }) +
      event("error", { code: "context_limit", message: "too late" });

    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(frames, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      ),
    );

    await streamChat(
      request,
      {
        onChunk: (chunk) => {
          onChunkCalls += 1;
          content.push(chunk);
        },
        onDone: () => {
          onDoneCalls += 1;
        },
        onError: () => {
          onErrorCalls += 1;
        },
        onAborted: () => {
          throw new Error("onAborted should not fire");
        },
      },
      undefined,
    );

    expect(onDoneCalls).toBe(1);
    expect(onChunkCalls).toBe(0);
    expect(content).toEqual([]);
    expect(onErrorCalls).toBe(0);
  });
});
