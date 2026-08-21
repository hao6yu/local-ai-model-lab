import { useState } from "react";
import type { EvalComparison, EvalResult, EvalRun, EvalRunBrief, EvalScoreSummary, EvalSideSummaries } from "../../types/evaluations";
import { getComparison, getComparisonExport } from "../../api/evaluations";

interface EvalComparisonProps {
  savedRuns: EvalRunBrief[];
  onClose(): void;
}

const SCORE_DIMENSIONS = ["accuracy", "completeness", "instruction_following", "appropriate_judgment"] as const;

function scoreSummaryText(summary: EvalScoreSummary | null): string {
  if (!summary || summary.mean_score === null || summary.scored_count === 0) {
    return "No scores yet";
  }
  return `${summary.mean_score.toFixed(2)} / 2 — ${summary.scored_count}/${summary.total_count} cases scored`;
}

function formatMetrics(result: EvalResult): string {
  const metrics = result.metrics;
  if (!metrics) return "";
  const parts: string[] = [];
  if (metrics.ttft_seconds !== null) parts.push(`TTFT ${metrics.ttft_seconds.toFixed(3)}s`);
  if (metrics.completion_seconds !== null) parts.push(`${metrics.completion_seconds.toFixed(3)}s`);
  if (metrics.generation_tps !== null)
    parts.push(`${metrics.generation_tps} tokens/s (${metrics.generation_tps_source ?? "upstream"})`);
  if (metrics.prompt_tokens !== null || metrics.completion_tokens !== null)
    parts.push(`${metrics.prompt_tokens ?? 0} prompt / ${metrics.completion_tokens ?? 0} completion`);
  return parts.join(" · ");
}

function scoreText(result: EvalResult): string {
  const scores = result.scores;
  if (!scores) return "Not scored";
  const present = SCORE_DIMENSIONS.filter((dim) => scores[dim] !== null);
  if (!present.length) return "Not scored";
  return present.map((dim) => `${dim.replace(/_/g, " ")}: ${scores[dim]}/2`).join(", ");
}

function flagText(result: EvalResult): string {
  const scores = result.scores;
  if (!scores) return "";
  const flags: string[] = [];
  if (scores.refusal) flags.push("Refusal");
  if (scores.hallucination) flags.push("Hallucination");
  if (scores.truncation) flags.push("Truncation");
  if (scores.unsafe_output) flags.push("Unsafe output");
  if (scores.format_failure) flags.push("Format failure");
  return flags.join(", ");
}

function noteText(result: EvalResult): string {
  const scores = result.scores;
  if (scores && scores.note) return scores.note;
  return "";
}

function CategoryList({ entries }: { entries: Record<string, EvalScoreSummary> }) {
  const names = Object.entries(entries).sort((a, b) => a[0].localeCompare(b[0]));
  if (!names.length) {
    return null;
  }
  return (
    <ul className="comparison-categories" data-testid="comparison-categories">
      {names.map(([name, summary]) => (
        <li key={name}>
          {name}: {scoreSummaryText(summary)}
        </li>
      ))}
    </ul>
  );
}

function SideProfile({ label, run, summaries }: { label: string; run: EvalRun; summaries: EvalSideSummaries }) {
  return (
    <div className="comparison-side" data-testid={`comparison-side-${label === "Left" ? "left" : "right"}`}>
      <h4>{label} — {run.profile_label}</h4>
      <dl className="comparison-settings">
        <dt>Model ID</dt>
        <dd>{run.model_id ?? "—"}</dd>
        <dt>Reasoning effort</dt>
        <dd>{run.reasoning_effort}</dd>
        <dt>Temperature</dt>
        <dd>{run.temperature ?? "—"}</dd>
        <dt>Max tokens</dt>
        <dd>{run.max_tokens ?? "—"}</dd>
        <dt>Context window</dt>
        <dd>{run.context_window ?? "—"}</dd>
        <dt>Notes</dt>
        <dd>{run.notes ?? "—"}</dd>
      </dl>
      <p data-testid={`comparison-side-${label === "Left" ? "left" : "right"}-summary`}>
        {scoreSummaryText(summaries.overall)}
      </p>
      <CategoryList entries={summaries.by_category} />
    </div>
  );
}

function ResultPair({ left, right, index, category, caseId }: { left: EvalResult; right: EvalResult | undefined; index: number; category: string | null; caseId: string }) {
  return (
    <section className="comparison-result-pair" data-testid="comparison-result" data-case-id={caseId}>
      <div data-testid={`comparison-case-${caseId}`}>
        <div className="comparison-result-header">
        Case {index} — {category ?? "uncategorized"}
      </div>
      <div className="comparison-result-prompt">{left.prompt}</div>
      <div className="comparison-result-columns">
        <div>
          <span className="comparison-side-label">Left</span>
          {left.error ? (
            <p className="comparison-result-error" data-testid="comparison-result-error">{left.error.message}</p>
          ) : (
            <p className="comparison-response">{left.response ?? "—"}</p>
          )}
          {formatMetrics(left) ? <p className="comparison-metrics">{formatMetrics(left)}</p> : null}
          <p className="comparison-scores">{scoreText(left)}</p>
          {flagText(left) ? <p className="comparison-result-flags">{flagText(left)}</p> : null}
          {noteText(left) ? (
            <p className="comparison-note" data-testid="comparison-result-note">{noteText(left)}</p>
          ) : null}
        </div>
        <div>
          <span className="comparison-side-label">Right</span>
          {right && right.error ? (
            <p className="comparison-result-error">{right.error.message}</p>
          ) : right ? (
            <p className="comparison-response">{right.response ?? "—"}</p>
          ) : (
            <p className="comparison-response">—</p>
          )}
          {right && formatMetrics(right) ? <p className="comparison-metrics">{formatMetrics(right)}</p> : null}
          <p className="comparison-scores">{right ? scoreText(right) : "—"}</p>
          {right && flagText(right) ? <p className="comparison-result-flags">{flagText(right)}</p> : null}
          {right && noteText(right) ? (
            <p className="comparison-note" data-testid="comparison-right-note">{noteText(right)}</p>
          ) : null}
        </div>
      </div>
      </div>
    </section>
  );
}

function ComparisonView({ comparison, onExport }: { comparison: EvalComparison; onExport(format: "markdown" | "json"): void }) {
  const { left, right, summaries } = comparison;
  const leftResults = [...left.results].sort((a, b) => a.index - b.index);
  const rightByCase = new Map<string, EvalResult>();
  for (const result of right.results) {
    rightByCase.set(result.case_id, result);
  }
  return (
    <>
      <h3>
        A/B comparison — {left.suite_name} · version {left.suite_version}
      </h3>
      <div className="comparison-actions">
        <button type="button" data-testid="export-markdown-button" onClick={() => onExport("markdown")}>
          Export Markdown
        </button>
        <button type="button" data-testid="export-json-button" onClick={() => onExport("json")}>
          Export JSON
        </button>
      </div>
      <div className="comparison-sides">
        <SideProfile label="Left" run={left} summaries={summaries.left} />
        <SideProfile label="Right" run={right} summaries={summaries.right} />
      </div>
      <div className="comparison-results">
        {leftResults.map((result) => {
          const right = rightByCase.get(result.case_id);
          return (
            <ResultPair
              key={result.case_id}
              left={result}
              right={right}
              index={result.index}
              category={result.category}
              caseId={result.case_id}
            />
          );
        })}
      </div>
    </>
  );
}

export function EvalComparison({ savedRuns, onClose }: EvalComparisonProps) {
  const [leftId, setLeftId] = useState<number | "">("");
  const [rightId, setRightId] = useState<number | "">("");
  const [comparison, setComparison] = useState<EvalComparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const left = Number(leftId);
  const right = Number(rightId);
  const bothSelected = leftId !== "" && rightId !== "";
  const canCompare = bothSelected && !Number.isNaN(left) && !Number.isNaN(right) && left !== right;

  const handleCompare = () => {
    if (!canCompare) return;
    setError(null);
    setComparison(null);
    setLoading(true);
    getComparison(left, right)
      .then((data) => {
        setComparison(data);
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "The comparison could not be loaded.");
      })
      .finally(() => setLoading(false));
  };

  const handleExport = (format: "markdown" | "json") => {
    if (!canCompare) return;
    setError(null);
    getComparisonExport(left, right, format)
      .then((content) => {
        const mime = format === "markdown" ? "text/markdown" : "application/json";
        const filename = format === "markdown" ? "comparison.md" : "comparison.json";
        const blob = new Blob([content], { type: mime });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "The export could not be downloaded.");
      });
  };

  return (
    <section className="comparison" data-testid="comparison-panel" aria-label="A/B run comparison">
      <h3>Compare saved runs</h3>
      <p className="detail">
        Select two finished runs and compare them side by side. Both runs must target the same suite name,
        version, and cases.
      </p>
      {error ? (
        <p className="status error" data-testid="comparison-error-banner">
          {error}
        </p>
      ) : null}
      {!comparison ? (
        <>
          <div className="comparison-selectors">
            <label>
              <span>Left run</span>
              <select
                data-testid="comparison-left-select"
                value={leftId}
                onChange={(event) => setLeftId(event.target.value === "" ? "" : Number(event.target.value))}
              >
                <option value="">— pick a run —</option>
                {savedRuns.map((run) => (
                  <option key={run.id} value={run.id}>
                    #{run.id} — {run.suite_name} · version {run.suite_version} · {run.state}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Right run</span>
              <select
                data-testid="comparison-right-select"
                value={rightId}
                onChange={(event) => setRightId(event.target.value === "" ? "" : Number(event.target.value))}
              >
                <option value="">— pick a run —</option>
                {savedRuns.map((run) => (
                  <option key={run.id} value={run.id}>
                    #{run.id} — {run.suite_name} · version {run.suite_version} · {run.state}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <button type="button" data-testid="compare-button" onClick={handleCompare} disabled={!canCompare || loading}>
            {loading ? "Comparing…" : "Compare runs"}
          </button>
          <button type="button" data-testid="comparison-close-button" onClick={onClose}>
            Close
          </button>
        </>
      ) : null}
      {comparison ? (
        <ComparisonView comparison={comparison} onExport={handleExport} />
      ) : null}
    </section>
  );
}
