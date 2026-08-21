# Implementation Plan

Each milestone should be a separately reviewable change. Do not combine milestones unless the user explicitly requests it.

## Milestone 1: project shell and health page

Deliver:

- Backend and frontend project skeletons using the documented stack.
- Environment-based configuration with a safe `.env.example`.
- `GET /api/health` and `GET /api/runtime`.
- A responsive page showing portal health, default-upstream reachability, every
  configured resident model, context declarations, and clear experimental badges.
- Developer commands in `README.md`.
- Backend and frontend unit tests for the health state.

Acceptance criteria:

- A fresh checkout can install and start both applications using documented commands.
- The page distinguishes portal healthy/model reachable from portal healthy/model unavailable.
- No upstream address, API key, authorization header, or secret is returned to the browser.
- Backend and frontend formatting, type checks, and tests pass.
- Services bind to loopback by default.

Do not implement chat, persistence, evaluation suites, or deployment in this milestone.

## Milestone 2: streaming text playground

Deliver:

- Streaming text chat through the backend provider adapter.
- A model selector populated from endpoint-safe backend metadata; changing it
  re-targets the next generation while retaining the conversation transcript,
  and never starts or stops a model container.
- New-chat, stop-generation, and clear-history controls.
- Reasoning selection: off, low, medium, high, and xhigh, while gracefully handling modes the provider ignores.
- Temperature and maximum completion-token settings.
- Visible TTFT, total time, token counts when reported, finish reason, and generation tokens/second when calculable.
- Useful upstream timeout, disconnect, malformed-stream, and context-limit errors.

Acceptance criteria:

- Long responses are not capped by an accidental frontend limit.
- Canceling generation closes the upstream request.
- No raw prompt or response is written to application logs.
- Streaming/provider tests use a fake upstream server and do not require the GX10.

## Milestone 3: evaluation suites and saved runs

Deliver:

- Versioned JSON suite schema and validation.
- The uncensored-behavior suite documented in `EVALUATION_SUITE.md`.
- SQLite schema and Alembic migrations.
- Sequential suite execution with progress and restart-safe run state.
- Result viewer with prompt, output, errors, performance measurements, settings snapshot, and profile label.
- Manual 0–2 scoring, notes, and flags.

Acceptance criteria:

- A completed run remains available after application restart.
- A failed test case is saved and does not erase completed cases.
- Only one evaluation executes at a time.
- Editing a suite after a run does not change the historical run snapshot.

## Milestone 4: serialized A/B comparison

Deliver:

- Compatibility checks requiring the same suite name/version and cases.
- Side-by-side responses and measurements.
- Per-category and overall score summaries without implying statistical significance.
- Export of a comparison to Markdown and machine-readable JSON.

Acceptance criteria:

- Runs from Ornith and Qwen (or later profiles) can be compared even though the
  portal executes them at different times.
- Missing/error results remain visible.
- Exports clearly identify model profile, quantization/runtime notes, settings, and suite version.

## Milestone 5: image evaluation

Full design decisions are recorded in `docs/M5_IMAGE_EVAL.md`. Summary:

Deliver:

- Browser upload of an image per case, validated by file bytes (not name or Content-Type).
- Accept JPEG, PNG, WebP, HEIC/HEIF, and GIF; 10 MiB maximum; one image per case.
- Transcode HEIC/HEIF and GIF to JPEG on the backend; the model always receives a JPEG.
- Data URL upstream transport to the OpenAI-compatible `/v1/chat/completions` endpoint.
- Vision case pairs with a deterministic transcription case (known transcription).
- Explicit case-type handling: UI separates exact transcription from interpretation; runs
  are rejected when a non-vision model (Ornith) is selected for an image case.
- Retention: images are stored with the saved run and deleted when the run is deleted.
- Saved-run image preview via a private backend endpoint.

Acceptance criteria:

- Invalid media never reaches the model endpoint.
- Image bytes and data URLs do not appear in normal logs.
- The UI separates exact transcription from inferred interpretation.

## Milestone 6: GX10 and Tailscale deployment

Deliver:

- Reproducible GX10 installation and service unit/container.
- Loopback-only portal binding.
- Tailscale Serve instructions with Funnel disabled.
- Backup and restore procedure for SQLite.
- Health checks after reboot.

Acceptance criteria:

- Portal works from an authorized Tailscale device while the Mac is asleep.
- The model API is not directly exposed through Tailscale Serve.
- Text, metrics, saved runs, image upload, restart, and backup restoration pass.

## Later possibilities

- Web-search evaluation with explicit external-data disclosure
- Automated judge/verifier runs using a separately configured model
- Repository/coding-agent benchmarks
- Multi-user authentication
- Controlled concurrency benchmarks
- Sampled video-frame understanding

These are not authorized by the current plan.
