import json
from collections import OrderedDict

from app.evaluations.schemas import (
    ComparisonResponse,
    EvalResultWithScores,
    EvalRunDetail,
    EvalScorePayload,
    ScoreSummary,
    SideSummaries,
    Summaries,
)

SCORE_DIMENSIONS = ("accuracy", "completeness", "instruction_following", "appropriate_judgment")


class ComparisonError(Exception):
    """Raised when two runs cannot be compared side by side."""


def _dimension_means(results: list[EvalResultWithScores]) -> list[float]:
    means: list[float] = []
    for dim in SCORE_DIMENSIONS:
        values = [
            getattr(result.scores, dim)
            for result in results
            if result.scores is not None and getattr(result.scores, dim) is not None
        ]
        if values:
            means.append(sum(values) / len(values))
    return means


def _score_summary(results: list[EvalResultWithScores]) -> ScoreSummary:
    means = _dimension_means(results)
    mean_score = round(sum(means) / len(means), 2) if means else None
    scored_count = sum(
        1
        for result in results
        if result.scores is not None
        and any(getattr(result.scores, dim) is not None for dim in SCORE_DIMENSIONS)
    )
    return ScoreSummary(mean_score=mean_score, scored_count=scored_count, total_count=len(results))


def _categorize(
    results: list[EvalResultWithScores],
) -> "OrderedDict[str, list[EvalResultWithScores]]":
    groups: OrderedDict[str, list[EvalResultWithScores]] = OrderedDict()
    for result in results:
        key = result.category or "Uncategorized"
        groups.setdefault(key, []).append(result)
    return groups


def side_summaries(run: EvalRunDetail) -> SideSummaries:
    by_category = {
        category: _score_summary(rows) for category, rows in _categorize(run.results).items()
    }
    return SideSummaries(overall=_score_summary(run.results), by_category=by_category)


def build_comparison_response(
    left: EvalRunDetail,
    right: EvalRunDetail,
) -> ComparisonResponse:
    return ComparisonResponse(
        left=left,
        right=right,
        summaries=Summaries(
            left=side_summaries(left),
            right=side_summaries(right),
        ),
    )


TERMINAL_RUN_STATES = ("completed", "failed")


def _require_finished(run: EvalRunDetail) -> None:
    if run.state not in TERMINAL_RUN_STATES:
        raise ComparisonError(f"Run {run.id} is {run.state}, so it is not finished yet.")


def assert_compatible(left: EvalRunDetail, right: EvalRunDetail) -> None:
    """Ensure two runs can be compared side by side.

    Both runs must be finished (state completed or failed) so every result is
    terminal, describe the same suite name and version, and cover exactly the
    same set of cases with matching prompts so results line up one to one.
    A finished run may still hold error results; those stay visible.
    """
    if left.id == right.id:
        raise ComparisonError("Select two different runs.")
    _require_finished(left)
    _require_finished(right)
    if left.suite_name != right.suite_name:
        raise ComparisonError(f"Suite name mismatch: '{left.suite_name}' vs '{right.suite_name}'.")
    if left.suite_version != right.suite_version:
        raise ComparisonError(
            f"Suite version mismatch: '{left.suite_version}' vs '{right.suite_version}'."
        )
    left_cases = {result.case_id: result.prompt for result in left.results}
    right_cases = {result.case_id: result.prompt for result in right.results}
    if left_cases != right_cases:
        raise ComparisonError("The two runs cover a different set of test cases or prompts.")


def _metric_segments(result: EvalResultWithScores) -> list[str]:
    metrics = result.metrics
    if metrics is None:
        return []
    segments: list[str] = []
    if metrics.ttft_seconds is not None:
        segments.append(f"TTFT {metrics.ttft_seconds:.3f}s")
    if metrics.completion_seconds is not None:
        segments.append(f"{metrics.completion_seconds:.3f}s")
    if metrics.generation_tps is not None:
        source = metrics.generation_tps_source or "upstream"
        segments.append(f"{metrics.generation_tps} tokens/s ({source})")
    if metrics.prompt_tokens is not None or metrics.completion_tokens is not None:
        segments.append(
            f"{metrics.prompt_tokens or 0} prompt / {metrics.completion_tokens or 0} completion"
        )
    return segments


def _score_summary_text(result: EvalResultWithScores) -> str:
    score = result.scores
    if score is None:
        return "—"
    parts: list[str] = []
    for dim in SCORE_DIMENSIONS:
        value = getattr(score, dim)
        label = dim.replace("_", " ")
        parts.append(f"{label}: {value}/2" if value is not None else f"{label}: —")
    return ", ".join(parts)


RESULT_FLAG_LABELS = (
    ("refusal", "Refusal"),
    ("hallucination", "Hallucination"),
    ("truncation", "Truncation"),
    ("unsafe_output", "Unsafe output"),
    ("format_failure", "Format failure"),
)


def _flags_text(scores: EvalScorePayload | None) -> str:
    if scores is None:
        return "—"
    flags = [label for attr, label in RESULT_FLAG_LABELS if getattr(scores, attr)]
    return "; ".join(flags) if flags else "—"


def _render_result_block(lines: list[str], label: str, result: EvalResultWithScores | None) -> None:
    lines.append(f"{label} response:")
    if result is None:
        lines.append("- —")
        return
    if result.error is not None:
        lines.append(f"- error: {result.error.message}")
    else:
        lines.append(f"- {result.response or '—'}")
    if result.metrics is not None:
        segments = _metric_segments(result)
        if segments:
            lines.append(f"- metrics: {'; '.join(segments)}")
    lines.append(f"- scores: {_score_summary_text(result)}")
    lines.append(f"- flags: {_flags_text(result.scores)}")
    if result.scores is not None and result.scores.note:
        lines.append(f"- note: {result.scores.note}")


def render_comparison_markdown(left: EvalRunDetail, right: EvalRunDetail) -> str:
    lines: list[str] = []
    lines.append("# A/B Comparison")
    lines.append("")
    lines.append(f"Suite: {left.suite_name} · version {left.suite_version} · {left.suite_hash}")
    lines.append("")

    for label, side in (("Left", left), ("Right", right)):
        lines.append(f"## {label} — {side.profile_label}")
        lines.append("")
        lines.append(f"- Model ID: {side.model_id or '—'}")
        lines.append(f"- Reasoning effort: {side.reasoning_effort}")
        lines.append(f"- Temperature: {side.temperature if side.temperature is not None else '—'}")
        lines.append(f"- Max tokens: {side.max_tokens if side.max_tokens is not None else '—'}")
        lines.append(
            f"- Context window: {side.context_window if side.context_window is not None else '—'}"
        )
        lines.append(f"- Notes: {side.notes or '—'}")
        summaries = side_summaries(side)
        overall = summaries.overall
        if overall is not None and overall.mean_score is not None:
            lines.append(
                f"- Summary: {overall.mean_score:.2f} / 2 "
                f"(scored {overall.scored_count}, {overall.total_count} cases)"
            )
        if summaries.by_category:
            lines.append("By category:")
            for category, stat in summaries.by_category.items():
                mean = f"{stat.mean_score:.2f} / 2" if stat.mean_score is not None else "—"
                lines.append(f"  - {category}: {mean} ({stat.scored_count}/{stat.total_count})")
        lines.append("")

    lines.append("## Results")
    lines.append("")
    right_by_case = {result.case_id: result for result in right.results}
    for left_result in sorted(left.results, key=lambda r: r.index):
        right_result = right_by_case.get(left_result.case_id)
        case = f"{left_result.category or 'Uncategorized'} ({left_result.case_id})"
        lines.append(f"### Case {left_result.case_id} — {case}")
        lines.append("")
        lines.append(f"Prompt: {left_result.prompt}")
        _render_result_block(lines, "Left", left_result)
        _render_result_block(lines, "Right", right_result)
        lines.append("")

    lines.append(
        "Notes: Manual mean of scored responses; small differences are descriptive, "
        "not significance tested."
    )
    lines.append("")
    return "\n".join(lines)


def render_comparison_json(left: EvalRunDetail, right: EvalRunDetail) -> str:
    left_dumped = left.model_dump(mode="json")
    right_dumped = right.model_dump(mode="json")
    payload = {
        "comparison": {
            "suite_name": left_dumped["suite_name"],
            "suite_version": left_dumped["suite_version"],
            "suite_hash": left_dumped["suite_hash"],
            "left_profile": left_dumped["profile_label"],
            "right_profile": right_dumped["profile_label"],
            "left_created_at": left_dumped["created_at"],
            "right_created_at": right_dumped["created_at"],
        },
        "summaries": {
            "left": side_summaries(left).model_dump(mode="json"),
            "right": side_summaries(right).model_dump(mode="json"),
        },
        "left": left_dumped,
        "right": right_dumped,
    }
    return json.dumps(payload, indent=2)
