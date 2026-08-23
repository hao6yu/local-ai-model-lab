import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RuntimeModel } from "../../types/health";
import { ChatPlayground } from "./ChatPlayground";

const models: RuntimeModel[] = [
  {
    key: "ornith",
    model_id: "ornith-1.5-35b-a3b",
    profile_label: "Ornith 1.5 35B-A3B NVFP4",
    context_window: 131072,
    experimental: false,
    default_reasoning_effort: "medium",
    default_max_tokens: 8192,
    supports_vision: false,
  },
  {
    key: "qwen",
    model_id: "qwen3.8-27b",
    profile_label: "Qwen3.8-27B NVFP4 + DFlash2",
    context_window: 131072,
    experimental: false,
    default_reasoning_effort: "low",
    default_max_tokens: 16384,
    supports_vision: true,
  },
];

function sse(...frames: string[]): string {
  return frames.join("");
}

function chunk(content: string): string {
  return "event: chunk\ndata: " + JSON.stringify({ content }) + "\n\n";
}

function done(finish_reason: string): string {
  const payload = {
    usage: { prompt_tokens: 3, completion_tokens: 2 },
    finish_reason,
    metrics: {
      ttft_seconds: 0.12,
      completion_seconds: 0.4,
      generation_tps: 5.0,
      token_source: "upstream",
    },
  };
  return "event: done\ndata: " + JSON.stringify(payload) + "\n\n";
}

function errorEvent(code: "context_limit" | "upstream_error", message: string): string {
  return "event: error\ndata: " + JSON.stringify({ code, message }) + "\n\n";
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ChatPlayground", () => {
  it("renders model, reasoning, temperature and token controls", () => {
    render(<ChatPlayground models={models} defaultModelProfile="ornith" />);

    expect(screen.getByTestId("model-selector")).toBeInTheDocument();
    expect(screen.getByTestId("reasoning-selector")).toBeInTheDocument();
    expect(screen.getByTestId("temperature-input")).toBeInTheDocument();
    expect(screen.getByTestId("max-tokens-input")).toBeInTheDocument();
    expect(screen.getByTestId("prompt-input")).toBeInTheDocument();
    expect(screen.getByText("ornith-1.5-35b-a3b")).toBeInTheDocument();
  });

  it("syncs reasoning + max tokens to the selected model's own defaults", () => {
    render(<ChatPlayground models={models} defaultModelProfile="ornith" />);
    const select = screen.getByTestId("model-selector") as HTMLSelectElement;
    const maxTokensInput = screen.getByTestId("max-tokens-input") as HTMLInputElement;
    const reasoningSelector = screen.getByTestId("reasoning-selector") as HTMLSelectElement;

    // ornith defaults = medium / 8192
    expect(reasoningSelector).toHaveValue("medium");
    expect(maxTokensInput.value).toBe("8192");

    // switching to qwen applies qwen's own defaults (low / 16384)
    select.value = "qwen";
    fireEvent.change(select);
    expect(reasoningSelector).toHaveValue("low");
    expect(maxTokensInput.value).toBe("16384");

    // switching back to ornith restores ornith's defaults (medium / 8192)
    select.value = "ornith";
    fireEvent.change(select);
    expect(reasoningSelector).toHaveValue("medium");
    expect(maxTokensInput.value).toBe("8192");
  });

  it("accumulates streamed content and reports the finish reason", async () => {
    const body = sse(
      chunk("Hel"),
      chunk("lo"),
      chunk("!"),
      done("stop"),
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

    render(<ChatPlayground models={models} defaultModelProfile="ornith" />);
    const input = screen.getByTestId("prompt-input") as HTMLTextAreaElement;
    fireEvent.input(input, { target: { value: "Hi" } });
    fireEvent.click(screen.getByTestId("send-button"));

    expect(await screen.findByText(/Hello!/)).toBeInTheDocument();
    expect(screen.getByTestId("status-indicator")).toHaveTextContent("Finish: stop");
    expect(screen.getByTestId("status-indicator")).toHaveTextContent("5 tokens/s");
    expect(screen.getByTestId("status-indicator")).toHaveTextContent("3 prompt / 2 completion (upstream)");
  });

  it("does not cap long streamed responses", async () => {
    const N = 500;
    const tokens = Array.from({ length: N }, (_unused, index) => String(index));
    const expected = tokens.join("") + "SENTINEL-TAIL";
    const frames = [
      ...tokens.map((token) => chunk(token)),
      chunk("SENTINEL-TAIL"),
      done("stop"),
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(sse(...frames), {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      ),
    );

    render(<ChatPlayground models={models} defaultModelProfile="ornith" />);
    const input = screen.getByTestId("prompt-input") as HTMLTextAreaElement;
    fireEvent.input(input, { target: { value: "long response" } });
    fireEvent.click(screen.getByTestId("send-button"));

    const assistant = await screen.findByText(/SENTINEL-TAIL/, { selector: ".playground-content" });
    expect(assistant.textContent).toBe(expected);
  });

  it("disables sending while generating and lets the user stop", async () => {
    let streamController: ReadableStreamDefaultController<Uint8Array> | null = null;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        streamController = controller;
        controller.enqueue(
          new TextEncoder().encode("event: chunk\ndata: " + JSON.stringify({ content: "x" }) + "\n\n"),
        );
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init: { signal?: AbortSignal } | undefined) => {
        const signal = init?.signal;
        if (signal) {
          signal.addEventListener("abort", () => {
            streamController?.error(new DOMException("Aborted", "AbortError"));
          });
        }
        return new Response(stream, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        });
      }),
    );

    render(<ChatPlayground models={models} defaultModelProfile="ornith" />);
    const input = screen.getByTestId("prompt-input") as HTMLTextAreaElement;
    fireEvent.input(input, { target: { value: "Go" } });
    fireEvent.click(screen.getByTestId("send-button"));

    expect(await screen.findByText(/x+/, { selector: ".playground-content" })).toBeInTheDocument();
    expect(screen.getByTestId("stop-button")).toBeEnabled();

    fireEvent.click(screen.getByTestId("stop-button"));

    await waitFor(() => {
      expect(screen.queryByTestId("status-indicator")).not.toBeInTheDocument();
    });
  });

  it("shows an upstream error event in the status line", async () => {
    const body = sse(
      errorEvent("context_limit", "Request exceeded the model's context window."),
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

    render(<ChatPlayground models={models} defaultModelProfile="ornith" />);
    const input = screen.getByTestId("prompt-input") as HTMLTextAreaElement;
    fireEvent.input(input, { target: { value: "Go" } });
    fireEvent.click(screen.getByTestId("send-button"));

    expect(await screen.findByTestId("error-banner")).toHaveTextContent(
      "Request exceeded the model's context window.",
    );
  });

  it("recovers from a non-SSE validation error and clears generating", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            detail: [{ loc: ["body", "max_tokens"], msg: "Input should be greater than 0" }],
          }),
          { status: 422, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    render(<ChatPlayground models={models} defaultModelProfile="qwen" />);
    const input = screen.getByTestId("prompt-input") as HTMLTextAreaElement;
    fireEvent.input(input, { target: { value: "Go" } });
    fireEvent.click(screen.getByTestId("send-button"));

    expect(await screen.findByTestId("error-banner")).toHaveTextContent(
      "max_tokens: Input should be greater than 0",
    );
    expect(screen.queryByTestId("status-indicator")).not.toBeInTheDocument();
  });

  it("clears the conversation with new chat", async () => {
    const body = sse(
      chunk("first"),
      done("stop"),
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

    render(<ChatPlayground models={models} defaultModelProfile="ornith" />);
    const input = screen.getByTestId("prompt-input") as HTMLTextAreaElement;
    fireEvent.input(input, { target: { value: "first prompt" } });
    fireEvent.click(screen.getByTestId("send-button"));
    await screen.findByText("first");

    fireEvent.click(screen.getByTestId("new-chat-button"));
    expect(screen.getByText("No messages yet. Start a chat above.")).toBeInTheDocument();
    expect(screen.getByTestId("prompt-input")).toHaveValue("");
  });

  it("clears a failing stream without leaving a blank assistant turn", async () => {
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

    render(<ChatPlayground models={models} defaultModelProfile="ornith" />);
    const input = screen.getByTestId("prompt-input");
    fireEvent.input(input, { target: { value: "Go" } });
    fireEvent.click(screen.getByTestId("send-button"));

    expect(await screen.findByTestId("error-banner")).toHaveTextContent(
      "The model stream was interrupted before completing.",
    );
    expect(screen.queryByTestId("status-indicator")).not.toBeInTheDocument();
    expect(document.querySelectorAll(".playground-message.message-assistant").length).toBe(0);
  });

  it("keeps partial content when a stream is interrupted", async () => {
    let phase = 0;
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (phase === 0) {
          phase = 1;
          controller.enqueue(
            new TextEncoder().encode(
              "event: chunk\ndata: " + JSON.stringify({ content: "par" }) + "\n\n",
            ),
          );
        } else {
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

    render(<ChatPlayground models={models} defaultModelProfile="ornith" />);
    const input = screen.getByTestId("prompt-input");
    fireEvent.input(input, { target: { value: "Go" } });
    fireEvent.click(screen.getByTestId("send-button"));

    expect(await screen.findByText("par", { selector: ".playground-content" })).toBeInTheDocument();
    expect(await screen.findByTestId("error-banner")).toBeInTheDocument();
    expect(document.querySelectorAll(".playground-message.message-assistant").length).toBe(1);
    expect(screen.queryByTestId("status-indicator")).not.toBeInTheDocument();
  });
});
