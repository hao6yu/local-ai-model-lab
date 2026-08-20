import { useEffect, useRef, useState } from "react";
import {
  createEvaluationRun,
  evaluateSuite,
  getEvaluationRun,
  getSuites,
  updateResultScore,
} from "../../api/evaluations";
import type {
  EvaluationRunRequest,
  EvalResult,
  EvalScore,
  EvalState,
  SuiteListItem,
} from "../../types/evaluations";
import { EMPTY_SCORE } from "../../types/evaluations";
import { ReasoningEffort } from "../../types/chat";

const REASONING_OPTIONS: ReasoningEffort[] = ["off", "low", "medium", "high", "xhigh"];

const NUMERIC_FIELDS: (keyof EvalScore)[] = [
  "accuracy",
  "completeness",
  "instruction_following",
  "appropriate_judgment",
];

const BOOLEAN_FIELDS: (keyof EvalScore)[] = [
  "refusal",
  "hallucination",
  "truncation",
  "unsafe_output",
  "failed",
];

type SuitesLoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; suites: SuiteListItem[] };

function formatMetrics(result: EvalResult): string {
  const metrics = result.metrics;
  if (!metrics) {
    return "";
  }
  const parts: string[] = [];
  if (metrics.ttft_seconds !== null) {
    parts.push(`TTFT ${metrics.ttft_seconds.toFixed(3)}s`);
  }
  if (metrics.completion_seconds !== null) {
    parts.push(`${metrics.completion_seconds.toFixed(3)}s`);
  }
  if (metrics.generation_tps !== null) {
    parts.push(`${metrics.generation_tps} tokens/s (${metrics.generation_tps_source ?? "upstream"})`);
  }
  if (metrics.prompt_tokens !== null || metrics.completion_tokens !== null) {
    parts.push(`${metrics.prompt_tokens ?? 0} prompt / ${metrics.completion_tokens ?? 0} completion`);
  }
  return parts.join(" · ");
}

export function EvaluationDashboard() {
  const [suitesState, setSuitesState] = useState<SuitesLoadState>({ kind: "loading" });
  const [selectedSuite, setSelectedSuite] = useState<string | null>(null);
  const [reasoningEffort, setReasoningEffort] = useState<ReasoningEffort>("off");
  const [profileLabel, setProfileLabel] = useState("assistant");
  const [notes, setNotes] = useState("");

  const [runId, setRunId] = useState<number | null>(null);
  const [state, setState] = useState<EvalState>("created");
  const [results, setResults] = useState<EvalResult[]>([]);
  const [progress, setProgress] = useState<{ case_index: number; total: number; status: EvalState } | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [scored, setScored] = useState<Record<number, EvalScore>>({});
  const [editingId, setEditingId] = useState<number | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getSuites(), Promise.resolve<void>(undefined)])
      .then(([suites]) => {
        if (!cancelled) {
          setSuitesState({ kind: "ready", suites: Array.isArray(suites) ? suites : [] });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setSuitesState({ kind: "error", message: error instanceof Error ? error.message : "Unknown error" });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const resetRun = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setRunId(null);
    setState("created");
    setResults([]);
    setProgress(null);
    setRunError(null);
    setScored({});
    setEditingId(null);
  };

  const selectedSuiteInfo =
    suitesState.kind === "ready"
      ? suitesState.suites.find((suite) => suite.name === selectedSuite)
      : null;

  const buildRequest = (): EvaluationRunRequest => ({
    suite_name: selectedSuiteInfo?.name ?? selectedSuite ?? "",
    suite_version: selectedSuiteInfo?.version ?? "1",
    reasoning_effort: reasoningEffort,
    temperature: null,
    max_tokens: null,
    profile_label: profileLabel,
    model_id: null,
    context_window: null,
    modality: "chat",
    notes: notes || null,
  });

  const startRun = () => {
    if (!selectedSuite || state === "running") {
      return;
    }
    const request = buildRequest();
    const controller = new AbortController();
    abortRef.current = controller;
    setProgress(null);
    setRunError(null);

    let streamFailed = false;
    createEvaluationRun(request)
      .then((id) => {
        setRunId(id);
        setState("running");
        return evaluateSuite(request, {
          onProgress: setProgress,
          onResult: () => {},
          onDone: () => {
            abortRef.current = null;
            setState("completed");
          },
          onError: (payload) => {
            abortRef.current = null;
            streamFailed = true;
            setState("failed");
            setRunError(payload.message);
          },
          onAborted: () => {
            abortRef.current = null;
            streamFailed = true;
            setState("failed");
            setRunError("The evaluation stream was interrupted before completing.");
          },
        }, controller.signal).then(() => {
          return streamFailed ? Promise.resolve(null) : getEvaluationRun(id);
        });
      })
      .then((run) => {
        if (run) {
          setResults(run.results);
          setState("completed");
        }
      })
      .catch(() => {
        abortRef.current = null;
      });
  };

  const handleScoreUpdate = (id: number, changes: Partial<EvalScore>) => {
    setScored((prev) => {
      const current = prev[id] ?? { ...EMPTY_SCORE };
      return { ...prev, [id]: { ...current, ...changes } };
    });
  };

  const saveScore = (id: number) => {
    const score = scored[id] ?? { ...EMPTY_SCORE };
    updateResultScore(id, score).then((updated) => {
      setResults((prev) => prev.map((result) => (result.id === id ? { ...result, scores: updated } : result)));
      setScored((prev) => ({ ...prev, [id]: updated }));
      setEditingId(null);
    });
  };

  return (
    <section className="eval" aria-label="Evaluation dashboard">
      <h2>Model evaluation suites</h2>
      <p className="detail">Run the default model on every case, review the outputs, and score each result from 0 to 2.</p>

      <section className="eval-controls">
        <label>
          <span>Suite</span>
          <select
            data-testid="suite-selector"
            value={selectedSuite ?? ""}
            onChange={(event) => setSelectedSuite(event.target.value || null)}
            disabled={state === "running"}
          >
            {suitesState.kind === "ready" && suitesState.suites.length === 0 ? (
              <option value="" disabled>
                No evaluation suites configured
              </option>
            ) : null}
            {suitesState.kind === "ready" && suitesState.suites.map((suite) => (
              <option key={`${suite.name}-${suite.version}`} value={suite.name}>
                {suite.name} · version {suite.version}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span>Reasoning effort</span>
          <select
            data-testid="reasoning-selector"
            value={reasoningEffort}
            onChange={(event) => setReasoningEffort(event.target.value as ReasoningEffort)}
            disabled={state === "running"}
          >
            {REASONING_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span>Profile label</span>
          <input
            data-testid="profile-label-input"
            value={profileLabel}
            placeholder="assistant"
            disabled={state === "running"}
            onChange={(event) => setProfileLabel(event.target.value)}
          />
        </label>

        <label>
          <span>Notes</span>
          <input
            data-testid="notes-input"
            value={notes}
            placeholder="Optional run notes"
            disabled={state === "running"}
            onChange={(event) => setNotes(event.target.value)}
          />
        </label>
      </section>

      {suitesState.kind === "loading" ? (
        <p className="status" data-testid="eval-status">Loading evaluation suites…</p>
      ) : null}

      {suitesState.kind === "error" ? (
        <p className="status error" data-testid="eval-status">
          Evaluation suites unavailable: {suitesState.message}
        </p>
      ) : null}

      {state === "running" && progress ? (
        <p className="eval-progress" data-testid="eval-progress">
          Evaluating case {progress.case_index + 1} of {progress.total}…
        </p>
      ) : null}

      {runError ? (
        <p className="status error" data-testid="eval-error-banner">
          {runError}
        </p>
      ) : null}

      {suitesState.kind === "ready" ? (
        <button
          type="button"
          data-testid="start-evaluation-button"
          disabled={state === "running" || !selectedSuite}
          onClick={startRun}
        >
          {state === "running" ? "Evaluating…" : "Start evaluation"}
        </button>
      ) : null}

      {runId !== null ? (
        <section className="eval-runs">
          <h3>
            Evaluation {runId} — <span className={`state state-${state}`}>{state}</span>
          </h3>
          <button type="button" data-testid="new-evaluation-button" onClick={resetRun}>
            New evaluation
          </button>
        </section>
      ) : null}

      {results.length > 0 ? (
        <section className="eval-results" data-testid="eval-results">
          {results.map((result) => (
            <ResultRow
              key={result.id}
              result={result}
              score={scored[result.id] ?? (result.scores ?? { ...EMPTY_SCORE })}
              metrics={formatMetrics(result)}
              isEditing={editingId === result.id}
              onField={(changes) => handleScoreUpdate(result.id, changes)}
              onEdit={() => setEditingId(result.id)}
              onSave={() => saveScore(result.id)}
              onCancel={() => setEditingId(null)}
            />
          ))}
        </section>
      ) : null}
    </section>
  );
}

interface ResultRowProps {
  result: EvalResult;
  score: EvalScore;
  metrics: string;
  isEditing: boolean;
  onField(changes: Partial<EvalScore>): void;
  onEdit(): void;
  onSave(): void;
  onCancel(): void;
}

function ResultRow({ result, score, metrics, isEditing, onField, onEdit, onSave, onCancel }: ResultRowProps) {
  const outcome = result.error ? "failed" : result.state;

  return (
    <article className="eval-result-card" data-testid="eval-result">
      <div className="eval-result-header">
        <span>
          Case {result.index} — {result.category ?? "uncategorized"}
        </span>
        <span className={`state state-${outcome}`}>{outcome}</span>
      </div>

      <p className="eval-result-prompt">{result.prompt}</p>
      {result.error ? (
        <p className="eval-result-error" data-testid="eval-result-error">
          {result.error.message}
        </p>
      ) : (
        <p className="eval-result-response" data-testid="eval-result-response">{result.response}</p>
      )}

      {metrics ? <p className="eval-metrics">{metrics}</p> : null}

      {isEditing ? (
        <div className="eval-score-form" data-testid="eval-score-form">
          <div className="eval-score-row">
            {NUMERIC_FIELDS.map((field) => (
              <label key={field}>
                <span>{String(field).replace(/_/g, " ")}</span>
                <select
                  value={String(score[field] ?? -1)}
                  onChange={(event) => onField({ [field]: event.target.value === "-1" ? null : Number(event.target.value) } as Partial<EvalScore>)}
                >
                  <option value="-1">—</option>
                  <option value="0">0</option>
                  <option value="1">1</option>
                  <option value="2">2</option>
                </select>
              </label>
            ))}
          </div>

          <div className="eval-score-row eval-checkbox-row">
            {BOOLEAN_FIELDS.map((field) => (
              <label key={field}>
                <input
                  type="checkbox"
                  checked={Boolean(score[field])}
                  onChange={(event) => onField({ [field]: event.target.checked } as Partial<EvalScore>)}
                />
                <span>{String(field).replace(/_/g, " ")}</span>
              </label>
            ))}
          </div>

          <label>
            <span>Note</span>
            <input
              className="eval-note-input"
              value={score.note ?? ""}
              onChange={(event) => onField({ note: event.target.value } as Partial<EvalScore>)}
            />
          </label>

          <div className="eval-buttons">
            <button type="button" className="eval-score-button" data-testid="eval-score-save-button" onClick={onSave}>
              Save score
            </button>
            <button type="button" className="eval-score-button eval-cancel-button" data-testid="eval-score-cancel-button" onClick={onCancel}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="eval-score-summary">
          {score.accuracy !== null || score.note ? (
            <span data-testid="eval-score-summary-text">
              Score {score.accuracy ?? "—"}/2{score.note ? ` — ${score.note}` : ""}
            </span>
          ) : null}
          <button
            type="button"
            className="eval-score-button eval-edit-button"
            onClick={onEdit}
            data-testid="eval-score-edit-button"
          >
            Score
          </button>
        </div>
      )}
    </article>
  );
}
