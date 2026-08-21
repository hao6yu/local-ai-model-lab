import { afterEach, describe, expect, it, vi } from "vitest";
import { createEvaluationRun, evaluateSuite, getSuites, getEvaluationRun, updateResultScore, getComparison, getComparisonExport } from "./evaluations";
import type { EvaluationRunRequest } from "../types/evaluations";
import { EMPTY_SCORE } from "../types/evaluations";

const runRequest: EvaluationRunRequest = {
  suite_name: "uncensored-behavior",
  suite_version: "1",
  reasoning_effort: "off",
  temperature: null,
  max_tokens: null,
  profile_label: "assistant",
  model_id: null,
  context_window: null,
  modality: "chat",
  notes: "test run",
  images: [],
};

function jsonBody(...frames: string[]): string {
  return frames.join("");
}

function event(name: string, payload: unknown): string {
  return `event: ${name}\ndata: ${JSON.stringify(payload)}\n\n`;
}

function progress(index: number, total: number, caseId: string): unknown {
  return { run_id: 1, case_index: index, total, case_id: caseId, status: "running" };
}

function result(index: number, total: number, caseId: string): unknown {
  return {
    run_id: 1,
    case_index: index,
    total,
    case_id: caseId,
    state: "completed",
    response: "No, I cannot help with that.",
    finish_reason: "stop",
    error: null,
    metrics: {
      ttft_seconds: 0.1,
      completion_seconds: 0.4,
      generation_tps: 8,
      generation_tps_source: "upstream",
      prompt_tokens: 20,
      completion_tokens: 10,
      token_source: "upstream",
      request_started_at: 1000,
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("evaluateSuite", () => {
  it("drives progress and result callbacks until done", async () => {
    const progresses: number[] = [];
    const results: string[] = [];
    let doneState: string | null = null;

    const body = jsonBody(
      event("progress", progress(0, 2, "U01")),
      event("result", result(0, 2, "U01")),
      event("progress", progress(1, 2, "U02")),
      event("result", result(1, 2, "U02")),
      event("done", { run_id: 1, state: "completed" }),
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

    await evaluateSuite(
      1,
      {
        onProgress: (payload) => progresses.push(payload.case_index),
        onResult: (payload) => results.push(payload.response ?? ""),
        onDone: (payload) => {
          doneState = payload.state;
        },
        onError: () => {
          throw new Error("onError should not fire");
        },
        onAborted: () => {
          throw new Error("onAborted should not fire");
        },
      },
      undefined,
    );

    expect(progresses).toEqual([0, 1]);
    expect(results).toEqual(["No, I cannot help with that.", "No, I cannot help with that."]);
    expect(doneState).toBe("completed");
  });

  it("surfaces a non-SSE conflict error instead of stalling", async () => {
    const captured: { code: string | null; message: string | null } = { code: null, message: null };
    const body = JSON.stringify({ detail: "Another evaluation run is already active." });

    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(body, {
          status: 409,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await evaluateSuite(
      1,
      {
        onProgress: () => {
          throw new Error("onProgress should not fire");
        },
        onResult: () => {
          throw new Error("onResult should not fire");
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
    expect(captured.message).toContain("Another evaluation run is already active");
  });

  it("reports onAborted when the stream is aborted", async () => {
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

    const promise = evaluateSuite(
      1,
      {
        onProgress: () => {
          throw new Error("onProgress should not fire");
        },
        onResult: () => {
          throw new Error("onResult should not fire");
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

    controller.abort();
    await promise;

    expect(aborted).toBe(true);
  });

  it("creates an evaluation run and returns its id", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn(async () =>
          new Response(JSON.stringify({ id: 42 }), {
            status: 201,
            headers: { "Content-Type": "application/json" },
          }),
        ),
      );

    const id = await createEvaluationRun(runRequest);
    expect(id).toBe(42);
  });

  it("updates a result score", async () => {
    const score: typeof EMPTY_SCORE = { ...EMPTY_SCORE, accuracy: 2, refusal: true, format_failure: true };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify(score), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const returned = await updateResultScore(7, score);
    expect(returned.accuracy).toBe(2);
  });

  it("loads an evaluation run", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ id: 7, state: "completed", total_cases: 1 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const run = await getEvaluationRun(7);
    expect(run.id).toBe(7);
  });

  it("loads the suite list", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify([{ name: "uncensored-behavior", version: 1, hash: "abc", case_count: 3, source_path: "/s" }]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const suites = await getSuites();
    expect(suites).toHaveLength(1);
    expect(suites[0].name).toBe("uncensored-behavior");
  });
});

describe("comparison API", () => {
  it("loads a comparison for two runs", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({
          left: { id: 1, state: "completed" },
          right: { id: 2, state: "completed" },
          summaries: { left: {}, right: {} },
        }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const data = await getComparison(1, 2);
    expect(data.left.id).toBe(1);
    expect(data.right.id).toBe(2);
    expect(data.summaries.left).toBeDefined();
    expect(data.summaries.right).toBeDefined();
  });

  it("returns the raw markdown from the export endpoint", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response("# A/B comparison", {
          status: 200,
          headers: { "Content-Type": "text/markdown" },
        }),
      ),
    );

    const text = await getComparisonExport(3, 4, "markdown");
    expect(text).toBe("# A/B comparison");
  });

  it("throws when the export endpoint returns an error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("nope", { status: 400, headers: { "Content-Type": "application/json" } })),
    );

    await expect(getComparisonExport(1, 2, "json")).rejects.toThrow(/failed with HTTP 400/);
  });
});
