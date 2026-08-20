import { useEffect, useRef, useState } from "react";
import { getRuntime } from "../../api/client";
import {
  createEvaluationRun,
  evaluateSuite,
  getEvaluationRun,
  getSuites,
  listSavedRuns,
  updateResultScore,
} from "../../api/evaluations";
import type {
  EvaluationRunRequest,
  EvalResult,
  EvalRun,
  EvalRunBrief,
  EvalScore,
  EvalState,
  SuiteListItem,
} from "../../types/evaluations";
import { EMPTY_SCORE } from "../../types/evaluations";
import type { RuntimeResponse } from "../../types/health";
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
  "format_failure",
];

function parseNumber(value: string): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

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
  const [runtime, setRuntime] = useState<RuntimeResponse | null>(null);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);
  const [useProfileSelect, setUseProfileSelect] = useState(false);
  const [profileValue, setProfileValue] = useState("assistant");
  const [temperature, setTemperature] = useState("");
  const [maxTokens, setMaxTokens] = useState("");
  const [savedRuns, setSavedRuns] = useState<EvalRunBrief[]>([]);
  const [savedRunsVisible, setSavedRunsVisible] = useState(false);
  const [selectedSuite, setSelectedSuite] = useState<string | null>(null);
  const [reasoningEffort, setReasoningEffort] = useState<ReasoningEffort>("off");
  const [notes, setNotes] = useState("");

  const [runId, setRunId] = useState<number | null>(null);
  const [state, setState] = useState<EvalState>("created");
  const [viewedRun, setViewedRun] = useState<EvalRun | null>(null);
  const [results, setResults] = useState<EvalResult[]>([]);
  const [progress, setProgress] = useState<{ case_index: number; total: number; status: EvalState } | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [scored, setScored] = useState<Record<number, EvalScore>>({});
  const [editingId, setEditingId] = useState<number | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let cancelled = false;

    getRuntime()
      .then((runtime) => {
        if (!cancelled) {
          setRuntime(runtime);
          const models = runtime.models ?? [];
          setUseProfileSelect(models.length > 1);
          if (models.length > 1) {
            const match = models.find((model) => model.model_id === runtime.model_id) ?? models[0];
            setProfileValue(match.model_id ?? match.key ?? "assistant");
          } else {
            setProfileValue(runtime.profile_label ?? (models[0]?.profile_label ?? "assistant"));
          }
          setMaxTokens(runtime.default_max_tokens != null ? String(runtime.default_max_tokens) : "");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRuntimeError("The runtime information could not be loaded.");
        }
      });

    getSuites()
      .then((suites) => {
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

  useEffect(() => {
    if (!savedRunsVisible) return;
    let cancelled = false;
    listSavedRuns()
      .then((runs) => {
        if (!cancelled) setSavedRuns(Array.isArray(runs) ? runs : []);
      })
      .catch(() => {
        if (!cancelled) setSavedRuns([]);
      });
    return () => {
      cancelled = true;
    };
  }, [savedRunsVisible]);

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
    setViewedRun(null);
  };

  const handleLoadRun = (run: EvalRunBrief) => {
    resetRun();
    setSavedRunsVisible(false);
    getEvaluationRun(run.id)
      .then((detail) => {
        setViewedRun(detail);
        setResults(detail.results ?? []);
        setState(detail.state);
      })
      .catch(() => {
        setRunError("This saved evaluation could not be loaded.");
        setState("failed");
      });
  };

  const selectedSuiteInfo =
    suitesState.kind === "ready"
      ? suitesState.suites.find((suite) => suite.name === selectedSuite)
      : null;

  const buildRequest = (): EvaluationRunRequest => {
    const model = (runtime?.models ?? []).find(
      (candidate) => candidate.model_id === profileValue || candidate.key === profileValue,
    );
    return {
      suite_name: selectedSuiteInfo?.name ?? selectedSuite ?? "",
      suite_version: selectedSuiteInfo?.version ?? "1",
      reasoning_effort: reasoningEffort,
      temperature: parseNumber(temperature) ?? null,
      max_tokens: parseNumber(maxTokens) ?? runtime?.default_max_tokens ?? null,
      profile_label: model?.profile_label ?? profileValue,
      model_id: model?.model_id ?? null,
      context_window: model?.context_window ?? runtime?.context_window ?? null,
      modality: "text",
      notes: notes || null,
    };
  };

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
    let doneFailed = false;
    createEvaluationRun(request)
      .then((id) => {
        setRunId(id);
        setState("running");
        return evaluateSuite(id, {
          onProgress: setProgress,
          onResult: () => {},
          onDone: (payload) => {
            abortRef.current = null;
            doneFailed = payload.state === "failed";
            setState(payload.state === "failed" ? "failed" : "completed");
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
          return getEvaluationRun(id);
        }).then((run) => {
          if (!run) return;
          setResults(run.results ?? []);
          if (!streamFailed && !doneFailed) {
            setState("completed");
          }
        });
      })
      .catch(() => {
        abortRef.current = null;
        setRunError("The evaluation could not be started.");
        setState("failed");
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

      {runtimeError ? (
        <p className="detail" data-testid="runtime-warning">
          Settings could not be pre-filled from the runtime: {runtimeError}
        </p>
      ) : null}

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

        {useProfileSelect ? (
          <label>
            <span>Profile</span>
            <select
              data-testid="profile-selector"
              value={profileValue}
              disabled={state === "running"}
              onChange={(event) => setProfileValue(event.target.value)}
            >
              {(runtime?.models ?? []).map((model) => (
                <option
                  key={model.key}
                  value={model.model_id ?? model.key}
                  title={model.profile_label ?? model.model_id ?? model.key}
                >
                  {model.model_id ?? model.key}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <label>
            <span>Profile label</span>
            <input
              data-testid="profile-label-input"
              value={profileValue}
              placeholder="assistant"
              disabled={state === "running"}
              onChange={(event) => setProfileValue(event.target.value)}
            />
          </label>
        )}

        <label>
          <span>Max tokens</span>
          <input
            data-testid="max-tokens-input"
            type="number"
            value={maxTokens}
            placeholder={runtime?.default_max_tokens != null ? String(runtime.default_max_tokens) : ""}
            disabled={state === "running"}
            onChange={(event) => setMaxTokens(event.target.value)}
          />
        </label>

        <label>
          <span>Temperature</span>
          <input
            data-testid="temperature-input"
            type="number"
            step="0.1"
            value={temperature}
            placeholder="default"
            disabled={state === "running"}
            onChange={(event) => setTemperature(event.target.value)}
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
          Evaluating case {progress.case_index} of {progress.total}…
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

      <section className="eval-saved-runs">
        <button
          type="button"
          data-testid="saved-runs-button"
          onClick={() => setSavedRunsVisible((visible) => !visible)}
        >
          {savedRunsVisible ? "Hide saved runs" : "Show saved runs"}
        </button>
        {savedRunsVisible ? (
          savedRuns.length === 0 ? (
            <p className="detail" data-testid="saved-runs-empty">No saved evaluations yet.</p>
          ) : (
            <ul data-testid="saved-runs-list">
              {savedRuns.map((run) => (
                <li
                  key={run.id}
                  className="saved-run-item"
                  data-testid={`saved-run-${run.id}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => handleLoadRun(run)}
                >
                  <span className={`state state-${run.state}`}>{run.state}</span>
                  <span>
                    #{run.id} — {run.suite_name} · version {run.suite_version}
                  </span>
                  <span>
                    {run.completed_cases} / {run.total_cases} · {new Date(run.created_at).toLocaleString()}
                  </span>
                </li>
              ))}
            </ul>
          )
        ) : null}
      </section>

      {viewedRun ? (
        <section className="eval-run-detail" data-testid="eval-run-detail">
          <h3>
            Loaded evaluation {viewedRun.id}
            <button type="button" data-testid="close-loaded-run-button" onClick={resetRun}>
              Close
            </button>
          </h3>
          <div className="eval-run-snapshot">
            <dl>
              <div>
                <dt>Suite</dt>
                <dd>
                  {viewedRun.suite_name} · version {viewedRun.suite_version}
                </dd>
              </div>
              <div>
                <dt>Profile label</dt>
                <dd>{viewedRun.profile_label}</dd>
              </div>
              <div>
                <dt>Model ID</dt>
                <dd>{viewedRun.model_id ?? "—"}</dd>
              </div>
              <div>
                <dt>Reasoning effort</dt>
                <dd>{viewedRun.reasoning_effort}</dd>
              </div>
              <div>
                <dt>Temperature</dt>
                <dd>{viewedRun.temperature ?? "—"}</dd>
              </div>
              <div>
                <dt>Max tokens</dt>
                <dd>{viewedRun.max_tokens ?? "—"}</dd>
              </div>
              <div>
                <dt>Context window</dt>
                <dd>{viewedRun.context_window ?? "—"}</dd>
              </div>
              {viewedRun.notes ? (
                <div>
                  <dt>Notes</dt>
                  <dd>{viewedRun.notes}</dd>
                </div>
              ) : null}
            </dl>
          </div>
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
