import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EvalComparison as EvalComparisonPayload, EvalRun, EvalRunBrief, EvalScore, EvalScoreSummary, EvalResult } from "../../types/evaluations";
import { EvalComparison } from "./EvalComparison";

const savedRuns: EvalRunBrief[] = [
  {
    id: 1,
    suite_name: "uncensored-behavior",
    suite_version: "1",
    state: "completed",
    created_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:00:01Z",
    completed_cases: 1,
    total_cases: 1,
  },
  {
    id: 2,
    suite_name: "uncensored-behavior",
    suite_version: "1",
    state: "completed",
    created_at: "2026-01-01T00:00:02Z",
    completed_at: "2026-01-01T00:00:03Z",
    completed_cases: 1,
    total_cases: 1,
  },
];

function scores(partial: Partial<EvalScore>): EvalScore {
  return {
    accuracy: null,
    completeness: null,
    instruction_following: null,
    appropriate_judgment: null,
    refusal: false,
    hallucination: false,
    truncation: false,
    unsafe_output: false,
    format_failure: false,
    note: null,
    ...partial,
  };
}

function runDetail(runId: number, profileLabel: string, runScores: EvalScore): EvalRun {
  return {
    id: runId,
    suite_name: "uncensored-behavior",
    suite_version: "1",
    suite_hash: "fa83",
    profile_label: profileLabel,
    model_id: profileLabel === "Ornith" ? "ornith-1.5-35b-a3b" : null,
    modality: "text",
    state: "completed",
    created_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:00:01Z",
    completed_cases: 1,
    total_cases: 1,
    reasoning_effort: "off",
    temperature: null,
    max_tokens: null,
    context_window: null,
    notes: null,
    suite_snapshot: "",
    results: [
      {
        id: runId * 10 + 1,
        case_id: "c1",
        index: 1,
        category: "general",
        prompt: "Question 1",
        response: "No, I cannot help with that.",
        finish_reason: "stop",
        error: null,
        metrics: null,
        state: "completed",
        input_type: "text",
        case_type: null,
        image_media_type: null,
        image_source: null,
        scores: runScores,
      },
    ],
  };
}

function result(
  id: number,
  caseId: string,
  index: number,
  response: string,
  score: EvalScore,
): EvalResult {
  return {
    id,
    case_id: caseId,
    index,
    category: "general",
    prompt: `Prompt ${caseId}`,
    response,
    finish_reason: "stop",
    error: null,
    metrics: null,
    state: "completed",
    input_type: "text",
    case_type: null,
    image_media_type: null,
    image_source: null,
    scores: score,
  };
}

function runDetailWithRuns(runId: number, profileLabel: string, runResults: EvalResult[]): EvalRun {
  return {
    id: runId,
    suite_name: "uncensored-behavior",
    suite_version: "1",
    suite_hash: "fa83",
    profile_label: profileLabel,
    model_id: profileLabel === "Ornith" ? "ornith-1.5-35b-a3b" : null,
    modality: "text",
    state: "completed",
    created_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:00:01Z",
    completed_cases: runResults.length,
    total_cases: runResults.length,
    reasoning_effort: "off",
    temperature: null,
    max_tokens: null,
    context_window: null,
    notes: null,
    suite_snapshot: "",
    results: runResults,
  };
}

function buildCustomComparison(leftResults: EvalResult[], rightResults: EvalResult[]): EvalComparisonPayload {
  const overall = (runResults: EvalResult[]): EvalScoreSummary => {
    const scored = runResults.filter((r) => r.scores?.accuracy !== null).length;
    const mean =
      scored > 0
        ? runResults.reduce((sum, r) => sum + (r.scores?.accuracy ?? 0), 0) / scored
        : null;
    return { mean_score: mean, scored_count: scored, total_count: runResults.length };
  };
  return {
    left: runDetailWithRuns(1, "Ornith", leftResults),
    right: runDetailWithRuns(2, "Qwen", rightResults),
    summaries: {
      left: { overall: overall(leftResults), by_category: { general: overall(leftResults) } },
      right: { overall: overall(rightResults), by_category: { general: overall(rightResults) } },
    },
  };
}

function buildComparison(leftScores: EvalScore, rightScores: EvalScore): EvalComparisonPayload {
  const leftOverall = {
    mean_score:
      (leftScores.accuracy ?? null) &&
      (leftScores.completeness ?? null) &&
      (leftScores.instruction_following ?? null) &&
      (leftScores.appropriate_judgment ?? null)
        ? (
            (leftScores.accuracy ?? 0) +
            (leftScores.completeness ?? 0) +
            (leftScores.instruction_following ?? 0) +
            (leftScores.appropriate_judgment ?? 0)
          ) / 4
        : null,
    scored_count:
      leftScores.accuracy !== null &&
      leftScores.completeness !== null &&
      leftScores.instruction_following !== null &&
      leftScores.appropriate_judgment !== null
        ? 1
        : 0,
    total_count: 1,
  };
  return {
    left: runDetail(1, "Ornith", leftScores),
    right: runDetail(2, "Qwen", rightScores),
    summaries: {
      left: { overall: leftOverall, by_category: { general: leftOverall } },
      right: {
        overall: {
          mean_score:
            rightScores.accuracy !== null
              ? rightScores.accuracy
              : null,
          scored_count: rightScores.accuracy !== null ? 1 : 0,
          total_count: 1,
        },
        by_category: {
          general: {
            mean_score: rightScores.accuracy !== null ? rightScores.accuracy : null,
            scored_count: rightScores.accuracy !== null ? 1 : 0,
            total_count: 1,
          },
        },
      },
    },
  };
}

function installBlobUrls(): { createObjectURL: ReturnType<typeof vi.fn>; revokeObjectURL: ReturnType<typeof vi.fn> } {
  const createObjectURL = vi.fn(() => "blob:mock");
  const revokeObjectURL = vi.fn(() => {});
  if (typeof URL.createObjectURL === "function") {
    vi.spyOn(URL, "createObjectURL").mockImplementation(createObjectURL);
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(revokeObjectURL);
  } else {
    (URL as { createObjectURL: unknown }).createObjectURL = createObjectURL;
    (URL as { revokeObjectURL: unknown }).revokeObjectURL = revokeObjectURL;
  }
  return { createObjectURL, revokeObjectURL };
}

function mockFetch(response: Response, matches: (path: string) => boolean) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => (matches(String(input)) ? response : new Response("{}", { status: 200 }))),
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("EvalComparison", () => {
  it("lists saved runs and disables compare until two are selected", () => {
    render(<EvalComparison savedRuns={savedRuns} onClose={() => {}} />);

    expect(screen.getByTestId("comparison-left-select")).toBeInTheDocument();
    expect(screen.getByTestId("comparison-right-select")).toBeInTheDocument();

    const compareButton = screen.getByTestId("compare-button");
    expect(compareButton).toBeDisabled();

    fireEvent.change(screen.getByTestId("comparison-left-select"), { target: { value: "1" } });
    expect(screen.getByTestId("compare-button")).toBeDisabled();

    fireEvent.change(screen.getByTestId("comparison-right-select"), { target: { value: "1" } });
    expect(screen.getByTestId("compare-button")).toBeDisabled();

    fireEvent.change(screen.getByTestId("comparison-right-select"), { target: { value: "2" } });
    expect(screen.getByTestId("compare-button")).toBeEnabled();
  });

  it("shows a side-by-side comparison with scores and no-score fallback", async () => {
    const comparison = buildComparison(
      scores({ accuracy: 2, completeness: 1, instruction_following: 2, appropriate_judgment: 1 }),
      scores({ accuracy: null, completeness: null }),
    );
    mockFetch(new Response(JSON.stringify(comparison), { status: 200, headers: { "Content-Type": "application/json" } }), (p) =>
      p.includes("/api/comparisons?left=1&right=2"),
    );
    render(<EvalComparison savedRuns={savedRuns} onClose={() => {}} />);

    fireEvent.change(screen.getByTestId("comparison-left-select"), { target: { value: "1" } });
    fireEvent.change(screen.getByTestId("comparison-right-select"), { target: { value: "2" } });
    fireEvent.click(screen.getByTestId("compare-button"));

    const leftSummary = await screen.findByTestId("comparison-side-left-summary");
    expect(leftSummary).toHaveTextContent("1.50 / 2");
    expect(leftSummary).toHaveTextContent("1/1 cases scored");
    expect(screen.getByTestId("comparison-side-right-summary")).toHaveTextContent("No scores yet");
    expect(screen.getAllByTestId("comparison-result")).toHaveLength(1);
    expect(screen.getAllByTestId("comparison-result")[0]).toHaveTextContent("Left");
    expect(screen.getAllByTestId("comparison-result")[0]).toHaveTextContent("Right");
  });

  it("reports a backend error below the selectors", async () => {
    mockFetch(
      new Response(JSON.stringify({ detail: "Select two different runs." }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      }),
      (p) => p.includes("/api/comparisons?left=1&right=2"),
    );
    render(<EvalComparison savedRuns={savedRuns} onClose={() => {}} />);

    fireEvent.change(screen.getByTestId("comparison-left-select"), { target: { value: "1" } });
    fireEvent.change(screen.getByTestId("comparison-right-select"), { target: { value: "2" } });
    fireEvent.click(screen.getByTestId("compare-button"));

    expect(await screen.findByTestId("comparison-error-banner")).toHaveTextContent("Select two different runs.");
    expect(screen.queryByTestId("comparison-result")).not.toBeInTheDocument();
  });

  it("exports markdown and json, requesting the matching format", async () => {
    const { createObjectURL, revokeObjectURL } = installBlobUrls();
    const clickLog: { filename: string }[] = [];
    const anchor = document.createElement("a");
    const clickSpy = vi.spyOn(anchor, "click").mockImplementation(() => {});
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => (tag === "a" ? anchor : originalCreateElement(tag)));

    const comparison = buildComparison(
      scores({ accuracy: 2, completeness: 1, instruction_following: 2, appropriate_judgment: 1 }),
      scores({ accuracy: 1, completeness: 2, instruction_following: 2, appropriate_judgment: 1 }),
    );
    const json = () => new Response(JSON.stringify(comparison), { status: 200, headers: { "Content-Type": "application/json" } });
    const markdown = () => new Response("# A/B comparison", { status: 200, headers: { "Content-Type": "text/markdown" } });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        if (!path.includes("/api/comparisons/export")) {
          return json();
        }
        return path.includes("format=json") ? json() : markdown();
      }),
    );
    render(<EvalComparison savedRuns={savedRuns} onClose={() => {}} />);

    fireEvent.change(screen.getByTestId("comparison-left-select"), { target: { value: "1" } });
    fireEvent.change(screen.getByTestId("comparison-right-select"), { target: { value: "2" } });

    fireEvent.click(screen.getByTestId("compare-button"));
    await screen.findByTestId("comparison-result");

    fireEvent.click(screen.getByTestId("export-markdown-button"));
    await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));
    clickLog.push({ filename: anchor.download });

    fireEvent.click(screen.getByTestId("export-json-button"));
    await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(2));
    clickLog.push({ filename: anchor.download });

    expect(clickSpy).toHaveBeenCalledTimes(2);
    expect(createObjectURL).toHaveBeenCalledTimes(2);
    expect(revokeObjectURL).toHaveBeenCalledTimes(2);
    expect(clickLog[0].filename).toBe("comparison.md");
    expect(clickLog[1].filename).toBe("comparison.json");
  });

  it("pairs results by case_id, not array index", async () => {
    const comparison = buildCustomComparison(
      [
        result(101, "c1", 1, "LEFT c1", scores({ accuracy: 2 })),
        result(102, "c2", 2, "LEFT c2", scores({ accuracy: 1 })),
      ],
      [
        result(201, "c1", 2, "RIGHT c1", scores({ accuracy: 2 })),
        result(202, "c2", 1, "RIGHT c2", scores({ accuracy: 1 })),
      ],
    );
    mockFetch(new Response(JSON.stringify(comparison), { status: 200, headers: { "Content-Type": "application/json" } }), (p) =>
      p.includes("/api/comparisons?left=1&right=2"),
    );
    render(<EvalComparison savedRuns={savedRuns} onClose={() => {}} />);

    fireEvent.change(screen.getByTestId("comparison-left-select"), { target: { value: "1" } });
    fireEvent.change(screen.getByTestId("comparison-right-select"), { target: { value: "2" } });
    fireEvent.click(screen.getByTestId("compare-button"));

    const c1 = await screen.findByTestId("comparison-case-c1");
    expect(c1).toHaveTextContent("LEFT c1");
    expect(c1).toHaveTextContent("RIGHT c1");
    const c2 = screen.getByTestId("comparison-case-c2");
    expect(c2).toHaveTextContent("LEFT c2");
    expect(c2).toHaveTextContent("RIGHT c2");
  });
});
