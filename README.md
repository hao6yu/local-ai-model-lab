# Local AI Model Lab

A private web portal for testing local language models on the ASUS Ascent GX10. The current targets are the Ornith and Qwen model families, each served through SGLang with official and experimental uncensored profiles.

This repository is intentionally documentation-first. Qwen/OpenCode should implement it one milestone at a time rather than inventing requirements while coding.

## What the portal should do

- Provide a clean streaming chat playground.
- Run reusable prompt suites against the currently loaded model.
- Record time to first token, completion time, token counts, and generation speed.
- Save model/profile metadata with every run.
- Support text first, then image inputs.
- Compare saved runs from two profiles side by side.
- Remain private to the local network or Tailscale.

The GX10 can hold multiple models resident at once, such as Ornith and Qwen, each served through its own SGLang endpoint. The portal switches between those profiles without restarting or switching any model. This application must not start, stop, load, or reload SGLang model containers.

## Read before coding

1. [AGENTS.md](AGENTS.md)
2. [Product specification](docs/PRODUCT_SPEC.md)
3. [Architecture](docs/ARCHITECTURE.md)
4. [Implementation plan](docs/IMPLEMENTATION_PLAN.md)
5. [Evaluation suite](docs/EVALUATION_SUITE.md)

## Development commands

Prerequisites: Python 3.12+ (a `python3` ≥ 3.12 on the PATH) and Node 18+ (Node 20/22 recommended).

### Backend (FastAPI, port 8000)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The backend exposes `GET /api/health`, `GET /api/runtime`, and
`POST /api/chat/stream`.

Configuration comes from environment variables (optionally a git-ignored
`backend/.env`). See `backend/.env.example`.

### Frontend (Vite dev server, port 5173, proxies `/api` to port 8000)

```bash
cd frontend
npm install
npm run dev
```

### Tests and checks

```bash
# Backend: unit tests, lint, formatting, and static type check
cd backend
python -m pytest
ruff check .
ruff format --check .
mypy

# Frontend: unit tests, type check, lint
cd frontend
npm test
npm run typecheck
npm run lint

# Frontend production build (type check + bundle)
npm run build
```

The backend uvicorn dev server and the Vite dev server both bind to
`127.0.0.1` by default.

## Recommended next prompt for Qwen/OpenCode

```text
Read AGENTS.md and every file under docs/. Implement the next incomplete
milestone in docs/IMPLEMENTATION_PLAN.md only. Do not implement other
milestones and do not change or restart the GX10 model service. Run the
specified tests, then report the files changed, commands run, test results,
and any unresolved decisions.
```

## Status

Milestones 1 and 2 are implemented. Milestone 1 delivers the project shell,
environment-based configuration, and `GET /api/health` plus `GET /api/runtime`;
`/api/health` now reports the state of every configured profile, not just the
default. Milestone 2 adds a streaming text playground: SSE streaming through
the backend provider adapter, model/reasoning/temperature/limit controls,
stop-generation, and new-chat, with TTFT, total time, token counts, and
generation throughput (reported only when reasoning is off, so hidden reasoning
tokens cannot inflate the figure) surfaced in the UI. A non-SSE response such as
an HTTP 422 validation error now surfaces as a recoverable error instead of
freezing the interface. Persistence (Milestone 3), evaluation suites, and
deployment remain unfinished.

