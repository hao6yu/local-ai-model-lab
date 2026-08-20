import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { HealthResponse, RuntimeResponse } from "../../types/health";
import { EvaluationDashboard } from "./EvaluationDashboard";
import type { EvalResult } from "../../types/evaluations";

const health: HealthResponse = {
  portal: "ok",
  model: { state: "reachable", detail: null },
  models: [],
};

const runtime: RuntimeResponse = {
  model_id: "ornith-1.5-35b-a3b",
  profile_label: "Ornith 1.5 35B-A3B NVFP4",
  context_window: 131072,
  experimental: false,
  default_reasoning_effort: "low",
  default_max_tokens: 16384,
  default_model_profile: "ornith",
  models: [],
};

const suites = [
  { name: "uncensored-behavior", version: 1, hash: "fa83", case_count: 2, source_path: "/s" },
];

const metrics = {
  ttft_seconds: 0.1,
  completion_seconds: 0.4,
  generation_tps: 8,
  generation_tps_source: "upstream",
  prompt_tokens: 20,
  completion_tokens: 10,
  token_source: "upstream" as const,
  request_started_at: 1000,
};

const results: EvalResult[] = [
  {
    id: 1,
    case_id: "U01",
    index: 1,
    category: "sensitive",
    prompt: "Prompt 1",
    response: "No, I can't help with that.",
    finish_reason: "stop",
    error: null,
    metrics,
    state: "completed",
    scores: null,
  },
  {
    id: 2,
    case_id: "U02",
    index: 2,
    category: "sensitive",
    prompt: "Prompt 2",
    response: "No, I can't help with that.",
    finish_reason: "stop",
    error: null,
    metrics,
    state: "completed",
    scores: null,
  },
];

type Recorded = { path: string; method: string; body: string | null };

interface MockConfig {
  streamBody: string;
  conflictStatus?: number;
  runId?: number;
  blockSuites?: boolean;
  score?: EvalResult["scores"];
}

function runDetail(runId: number): unknown {
  return {
    id: runId,
    suite_name: "uncensored-behavior",
    suite_version: 1,
    suite_hash: "fa83",
    profile_label: "assistant",
    model_id: null,
    modality: "chat",
    state: "completed",
    created_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:00:01Z",
    completed_cases: results.length,
    total_cases: results.length,
    reasoning_effort: "off",
    temperature: null,
    max_tokens: null,
    context_window: null,
    notes: null,
    results,
  };
}

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function mockApis(config: MockConfig) {
  const runId = config.runId ?? 42;
  const recorded: Recorded[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ?? null;
    recorded.push({ path, method, body: typeof body === "string" ? body : null });
    if (config.blockSuites && path.endsWith("/api/suites")) {
      await new Promise(() => {});
      return new Response("{}");
    }
    if (path.endsWith("/api/health")) {
      return json(health);
    }
    if (path.endsWith("/api/runtime")) {
      return json(runtime);
    }
    if (path.endsWith("/api/suites")) {
      return json(suites);
    }
    if (path.endsWith("/api/evaluation-runs") && method === "POST") {
      return new Response(JSON.stringify({ run_id: runId }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (path.endsWith("/api/evaluation-runs/start")) {
      if (config.conflictStatus) {
        return new Response(JSON.stringify({ detail: "Another evaluation run is already active." }), {
          status: config.conflictStatus,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(config.streamBody, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      });
    }
    if (path.startsWith("/api/evaluation-runs/")) {
      return json(runDetail(runId));
    }
    if (path.startsWith("/api/results/")) {
      if (config.score) {
        return json(config.score);
      }
      try {
        return json(JSON.parse(body as string));
      } catch {
        return json(null);
      }
    }
    return json({ detail: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, recorded };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function event(name: string, payload: unknown): string {
  return `event: ${name}\ndata: ${JSON.stringify(payload)}\n\n`;
}

function progress(index: number, total: number, caseId: string): unknown {
  return { run_id: 42, case_index: index, total, case_id: caseId, status: "running" };
}

function resultFrame(index: number, total: number, caseId: string): unknown {
  return {
    run_id: 42,
    case_index: index,
    total,
    case_id: caseId,
    state: "completed",
    response: "No, I can't help with that.",
    finish_reason: "stop",
    error: null,
    metrics,
  };
}

describe("EvaluationDashboard", () => {
  it("shows a loading state before suites respond", async () => {
    mockApis({ streamBody: "", blockSuites: true });
    render(<EvaluationDashboard />);
    expect(await screen.findByTestId("eval-status")).toHaveTextContent("Loading evaluation suites");
  });

  it("disables the start button until a suite is selected", async () => {
    mockApis({ streamBody: "" });
    render(<EvaluationDashboard />);

    const startButton = await screen.findByTestId("start-evaluation-button");
    expect(startButton).toBeDisabled();

    fireEvent.change(screen.getByTestId("suite-selector"), {
      target: { value: "uncensored-behavior" },
    });
    expect(screen.getByTestId("start-evaluation-button")).toBeEnabled();
  });

  it("streams results and renders scored cards", async () => {
    const streamBody =
      event("progress", progress(0, 2, "U01")) +
      event("result", resultFrame(0, 2, "U01")) +
      event("progress", progress(1, 2, "U02")) +
      event("result", resultFrame(1, 2, "U02")) +
      event("done", { run_id: 42, state: "completed" });
    mockApis({ streamBody });
    render(<EvaluationDashboard />);

    const startButton = await screen.findByTestId("start-evaluation-button");
    fireEvent.change(screen.getByTestId("suite-selector"), {
      target: { value: "uncensored-behavior" },
    });
    fireEvent.click(startButton);

    await screen.findByTestId("eval-results");

    fireEvent.change(screen.getByTestId("reasoning-selector"), {
      target: { value: "medium" },
    });
    fireEvent.change(screen.getByTestId("profile-label-input"), {
      target: { value: "assistant" },
    });

    expect(await screen.findByTestId("eval-results")).toBeInTheDocument();
    expect(screen.getAllByTestId("eval-result")).toHaveLength(2);
  });

  it("saves a manual score through PATCH", async () => {
    const { recorded } = mockApis({
      streamBody: event("done", { run_id: 42, state: "completed" }),
      score: {
        accuracy: 2,
        completeness: null,
        instruction_following: null,
        appropriate_judgment: null,
        refusal: true,
        hallucination: false,
        truncation: false,
        unsafe_output: false,
        failed: false,
        note: "Clear refusal",
      },
    });
    render(<EvaluationDashboard />);

    const startButton = await screen.findByTestId("start-evaluation-button");
    fireEvent.change(screen.getByTestId("suite-selector"), {
      target: { value: "uncensored-behavior" },
    });
    fireEvent.click(startButton);

    await screen.findByTestId("eval-results");

    fireEvent.click(screen.getAllByTestId("eval-score-edit-button")[0]);
    const form = within(screen.getAllByTestId("eval-score-form")[0]);
    const selects = form.getAllByRole("combobox") as HTMLSelectElement[];
    fireEvent.change(selects[0], { target: { value: "2" } });
    fireEvent.click(form.getByTestId("eval-score-save-button"));

    expect(recorded.some((entry) => entry.method === "PATCH" && entry.path.includes("/api/results/1/") && entry.body?.includes('"accuracy":2'))).toBe(true);

    expect(await screen.findByTestId("eval-score-summary-text")).toHaveTextContent("Score 2/2");
  });

  it("reports a conflict as an error instead of stalling", async () => {
    const { recorded } = mockApis({ streamBody: "", conflictStatus: 409 });
    render(<EvaluationDashboard />);

    const button = await screen.findByTestId("start-evaluation-button");
    fireEvent.change(screen.getByTestId("suite-selector"), {
      target: { value: "uncensored-behavior" },
    });
    fireEvent.click(button);

    await screen.findByTestId("eval-error-banner");

    expect(recorded.some((r) => r.method === "POST" && r.path.endsWith("/api/evaluation-runs/start"))).toBe(true);
    expect(await screen.findByTestId("eval-error-banner")).toHaveTextContent("Another evaluation run is already active");
  });
});
