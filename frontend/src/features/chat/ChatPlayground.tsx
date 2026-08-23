import { useEffect, useRef, useState } from "react";
import type { ChatMessage, ChatErrorPayload, ChatDonePayload, ChatStreamRequest, ReasoningEffort } from "../../types/chat";
import type { RuntimeModel } from "../../types/health";
import { streamChat } from "../../api/chatStream";

const REASONING_OPTIONS: ReasoningEffort[] = ["off", "low", "medium", "high", "xhigh", "max"];

interface ChatPlaygroundProps {
  models: RuntimeModel[];
  defaultModelProfile: string | null;
}

function toEffort(value: string | null | undefined): ReasoningEffort {
  return (REASONING_OPTIONS as string[]).includes(value ?? "")
    ? (value as ReasoningEffort)
    : "off";
}

function formatError(payload: ChatErrorPayload): string {
  const fallbacks: Record<ChatErrorPayload["code"], string> = {
    not_configured: "The model endpoint is not configured.",
    upstream_timeout: "The model endpoint timed out before responding.",
    disconnected: "The model endpoint connection failed.",
    upstream_error: "The model endpoint rejected the request.",
    context_limit: "The request exceeded the model's context window.",
    malformed_stream: "The model endpoint sent a malformed stream response.",
    stream_error: "The model stream was interrupted before completing.",
  };
  return payload.message || fallbacks[payload.code];
}

function formatDone(payload: ChatDonePayload): string {
  const metrics = payload.metrics;
  const parts: string[] = [];
  if (metrics.ttft_seconds !== null) {
    parts.push(`TTFT ${metrics.ttft_seconds.toFixed(3)}s`);
  }
  parts.push(`Total ${metrics.completion_seconds.toFixed(3)}s`);
  if (metrics.generation_tps !== null) {
    parts.push(`${metrics.generation_tps} tokens/s`);
  }
  if (payload.usage) {
    const { prompt_tokens, completion_tokens } = payload.usage;
    if (prompt_tokens !== null || completion_tokens !== null) {
      parts.push(
        `${prompt_tokens ?? 0} prompt / ${completion_tokens ?? 0} completion (upstream)`,
      );
    }
  }
  if (payload.finish_reason !== null) {
    parts.push(`Finish: ${payload.finish_reason}`);
  }
  return `Done — ${parts.join(" · ")}`;
}

function pruneEmptyAssistant(messages: ChatMessage[]): ChatMessage[] {
  return messages.filter((message) => !(message.role === "assistant" && message.content === ""));
}

export function ChatPlayground({ models, defaultModelProfile }: ChatPlaygroundProps) {
  const abortRef = useRef<AbortController | null>(null);

  const resolvedDefault = models.find((model) => model.key === defaultModelProfile) ?? models[0];

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [prompt, setPrompt] = useState("");
  const [modelProfile, setModelProfile] = useState<string | null>(
    resolvedDefault?.key ?? defaultModelProfile,
  );
  const [reasoningEffort, setReasoningEffort] = useState<ReasoningEffort>(
    toEffort(resolvedDefault?.default_reasoning_effort),
  );
  const [temperature, setTemperature] = useState<number | null>(null);
  const [maxTokens, setMaxTokens] = useState<number | null>(
    resolvedDefault?.default_max_tokens ?? null,
  );
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<ChatErrorPayload | null>(null);
  const [done, setDone] = useState<ChatDonePayload | null>(null);

  const canSend = prompt.trim().length > 0 && !generating;

  const stopGeneration = () => {
    abortRef.current?.abort();
  };

  const resetSession = () => {
    stopGeneration();
    abortRef.current = null;
    setMessages([]);
    setPrompt("");
    setError(null);
    setDone(null);
    setGenerating(false);
  };

  const sendMessage = () => {
    const current = prompt.trim();
    if (!canSend) {
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;

    setMessages((prev) => [
      ...prev,
      { role: "user", content: current },
      { role: "assistant", content: "" },
    ]);
    setError(null);
    setDone(null);
    setGenerating(true);
    setPrompt("");

    const request: ChatStreamRequest = {
      model_profile: modelProfile,
      messages: [...messages, { role: "user", content: current }],
      temperature,
      max_tokens: maxTokens,
      reasoning_effort: reasoningEffort,
    };

    streamChat(
      request,
      {
        onChunk: (content) => {
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last && last.role === "assistant") {
              next[next.length - 1] = { ...last, content: last.content + content };
            }
            return next;
          });
        },
        onDone: (payload) => {
          setDone(payload);
          setMessages((prev) => pruneEmptyAssistant(prev));
          setGenerating(false);
          abortRef.current = null;
        },
        onError: (payload) => {
          setError(payload);
          setMessages((prev) => pruneEmptyAssistant(prev));
          setGenerating(false);
          abortRef.current = null;
        },
        onAborted: () => {
          setGenerating(false);
          setMessages((prev) => pruneEmptyAssistant(prev));
          abortRef.current = null;
          setError(null);
        },
      },
      controller.signal,
    );
  };

  useEffect(() => () => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  const applyModelDefaults = (key: string | null) => {
    const model = models.find((m) => m.key === key);
    if (!model) {
      return;
    }
    // Sync the thinking controls to the selected model's own profile defaults so
    // each model starts with its own reasoning effort / token budget.
    setReasoningEffort(toEffort(model.default_reasoning_effort));
    setMaxTokens(model.default_max_tokens ?? null);
  };

  return (
    <section className="playground" aria-label="Streaming chat playground">
      <section className="playground-options">
        <label>
          <span>Model</span>
          <select
            data-testid="model-selector"
            value={modelProfile ?? ""}
            onChange={(event) => {
              const key = event.target.value || null;
              setModelProfile(key);
              applyModelDefaults(key);
            }}
            disabled={generating}
          >
            {models.length === 0 ? (
              <option value="" disabled>
                No models configured
              </option>
            ) : null}
            {models.map((model) => (
              <option
                key={model.key}
                value={model.key}
                title={model.profile_label ?? model.model_id ?? model.key}
              >
                {model.model_id ?? model.key}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Reasoning</span>
          <select
            data-testid="reasoning-selector"
            value={reasoningEffort}
            onChange={(event) => setReasoningEffort(event.target.value as ReasoningEffort)}
            disabled={generating}
          >
            {REASONING_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Temperature</span>
          <input
            data-testid="temperature-input"
            type="number"
            min={0}
            max={2}
            step={0.1}
            value={temperature ?? ""}
            placeholder="default"
            disabled={generating}
            onChange={(event) =>
              setTemperature(event.target.value === "" ? null : Number(event.target.value))
            }
          />
        </label>
        <label>
          <span>Max tokens</span>
          <input
            data-testid="max-tokens-input"
            type="number"
            min={1}
            value={maxTokens ?? ""}
            placeholder="default"
            disabled={generating}
            onChange={(event) =>
              setMaxTokens(event.target.value === "" ? null : Number(event.target.value))
            }
          />
        </label>
      </section>

      <section className="playground-messages" data-testid="messages">
        {messages.length === 0 ? (
          <p className="playground-empty">No messages yet. Start a chat above.</p>
        ) : (
          messages.map((message, index) => (
            <div key={index} className={`playground-message message-${message.role}`}>
              <span className="playground-role">{message.role}</span>
              <span className="playground-content">{message.content}</span>
            </div>
          ))
        )}
      </section>

      <section className="playground-status">
        {error ? (
          <p className="status error" data-testid="error-banner">
            {formatError(error)}
          </p>
        ) : null}
        {done ? (
          <p className="playground-status-indicator" data-testid="status-indicator">
            {formatDone(done)}
          </p>
        ) : null}
        {generating ? (
          <p className="playground-status-indicator" data-testid="status-indicator">
            Generating…
          </p>
        ) : null}
      </section>

      <section className="playground-controls">
        <textarea
          data-testid="prompt-input"
          rows={3}
          placeholder="Message the model. Enter to send, Shift+Enter for a new line."
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          disabled={generating}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              sendMessage();
            }
          }}
        />
        <div className="playground-buttons">
          <button type="button" data-testid="send-button" disabled={!canSend} onClick={sendMessage}>
            Send
          </button>
          <button type="button" data-testid="stop-button" disabled={!generating} onClick={stopGeneration}>
            Stop
          </button>
          <button type="button" data-testid="new-chat-button" onClick={resetSession}>
            New chat
          </button>
        </div>
      </section>
    </section>
  );
}
