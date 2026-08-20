# Architecture

## Chosen stack

- Backend: Python 3.12, FastAPI, Pydantic, SQLAlchemy, Alembic, SQLite
- Frontend: React, TypeScript, Vite
- Streaming: Server-Sent Events from backend to browser
- Testing: pytest for backend; Vitest and React Testing Library for frontend
- Formatting and checks: Ruff for Python; ESLint and TypeScript for frontend

This stack keeps the model adapter and private data on the server while allowing a responsive test and comparison UI. The portal itself requires no CUDA libraries.

## Runtime topology

### Development on the Mac

```text
Mac browser
    |
    v
React/Vite + FastAPI on 127.0.0.1
    |
    v
SSH tunnels on 127.0.0.1:30000 and :30001
    |
    v
GX10 SGLang: Ornith on :30000, Qwen on :30001
```

### Intended GX10 deployment

```text
Mac/phone browser
    |
    | Tailscale HTTPS only
    v
GX10 portal on 127.0.0.1:8081
    |
    v
GX10 SGLang on 127.0.0.1:30000 and :30001
```

The GX10 topology is preferred after development because the portal remains
available without keeping the Mac awake and image uploads do not travel through
the Mac. Both inference endpoints remain loopback-only, the backend chooses the
configured endpoint, and Tailscale Funnel remains disabled.

## Backend modules

```text
backend/app/
  api/                 HTTP routes and SSE endpoints
  core/                configuration and application lifecycle
  db/                  SQLAlchemy models, sessions, migrations
  model_provider/      OpenAI-compatible adapter
  evaluations/         suite loading, run orchestration, metrics
  schemas/             request/response models
  main.py              FastAPI application
```

The provider adapter owns upstream request construction and stream parsing. API routes must not contain SGLang-specific behavior.

## Frontend modules

```text
frontend/src/
  api/                  typed backend client and streaming transport
  components/           reusable UI components
  features/chat/        chat playground
  features/evaluations/ suite runner and scoring
  features/comparisons/ saved-run A/B view
  pages/                route-level components
  types/                shared frontend types
```

## Persistence model

The initial SQLite database contains:

- `model_profiles`: display label and descriptive metadata
- `test_suites`: name, version, and immutable suite content hash
- `evaluation_runs`: profile/settings snapshot and run state
- `evaluation_results`: prompt, response, measurements, error, and finish reason
- `manual_scores`: four scores, flags, and notes

Chat playground history can remain browser-local initially. Evaluation results belong in SQLite.

Suite source files live as versioned JSON under `data/suites/`. When a run begins, the suite content and hash are copied into the run snapshot so later edits do not rewrite history.

## API outline

The exact response schemas should be defined during implementation, but the route boundary is:

- `GET /api/health`: portal and upstream reachability
- `GET /api/runtime`: configured endpoint-safe metadata and profile label
- `POST /api/chat/stream`: streaming chat proxy
- `GET /api/suites`: available suites and versions
- `POST /api/evaluation-runs`: create a run
- `POST /api/evaluation-runs/{id}/start`: execute sequentially via SSE
- `GET /api/evaluation-runs/{id}`: run and result details
- `PATCH /api/results/{id}/score`: manual scores and flags
- `GET /api/comparisons?left={id}&right={id}`: compatible side-by-side data

The browser never calls SGLang directly.

## Streaming and metrics

For each request, the backend records a monotonic start time. TTFT ends when the first non-empty assistant-content fragment is received. Completion time ends when the upstream stream finishes or errors.

Preferred token accounting order:

1. Upstream usage fields returned with the streaming response
2. A tokenizer specifically matching the configured model
3. No token metric

Do not label character-based estimates as tokens. Calculated generation rate is `completion_tokens / (completion_time - ttft)` only when completion tokens are reliable and the denominator is positive.

## Concurrency

The MVP evaluation runner has one worker and executes one case at a time. It
rejects or queues a second evaluation run. Both models may remain resident, but
the portal does not generate from them concurrently. This keeps measurements
comparable and avoids competing for unified memory.

## Configuration

Preferred dual-resident configuration (shown formatted here; `.env` stores the
JSON on one line):

```json
[
  {"key":"ornith","api_base":"http://127.0.0.1:30000/v1","model_id":"ornith-1.5-35b-a3b","context_window":131072,"default_reasoning_effort":"medium","default_max_tokens":16384},
  {"key":"qwen","api_base":"http://127.0.0.1:30001/v1","model_id":"qwen3.8-27b","context_window":131072,"default_reasoning_effort":"low","default_max_tokens":16384}
]
```

```text
MODEL_PROFILES_JSON=<the JSON list above>
DEFAULT_MODEL_PROFILE=ornith
MODEL_API_KEY=
DATABASE_URL=sqlite:///./data/model-lab.db
```

The older `MODEL_API_BASE`, `MODEL_ID`, and related variables remain a
backward-compatible one-endpoint fallback. Neither API base is returned to the
browser.

An `.env.example` may contain safe placeholders. `.env` must be ignored.

## Deployment boundary

Deployment is a later milestone. Prefer a systemd service or a small multi-architecture container on the GX10. Bind the application to loopback and publish it only with Tailscale Serve. Preserve the current Mac portal as a fallback until the new portal passes text, web UI, vision, restart, and Tailscale tests.
