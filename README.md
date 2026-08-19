# Local AI Model Lab

A private web portal for testing local language models on the ASUS Ascent GX10. The first target is Qwen3.8-27B, including the official and experimental uncensored profiles already served through SGLang.

This repository is intentionally documentation-first. Qwen/OpenCode should implement it one milestone at a time rather than inventing requirements while coding.

## What the portal should do

- Provide a clean streaming chat playground.
- Run reusable prompt suites against the currently loaded model.
- Record time to first token, completion time, token counts, and generation speed.
- Save model/profile metadata with every run.
- Support text first, then image inputs.
- Compare saved runs from two profiles side by side.
- Remain private to the local network or Tailscale.

The GX10 should continue loading only one large model at a time. An A/B comparison means running a suite with profile A, switching the model through the existing GX10 management scripts, running it again with profile B, and comparing the saved results. This application must not load or stop models in its first release.

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

Both backend endpoints are `GET /api/health` and `GET /api/runtime`.

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

## Recommended first prompt for Qwen/OpenCode

```text
Read AGENTS.md and every file under docs/. Implement Milestone 1 from
docs/IMPLEMENTATION_PLAN.md only. Do not implement later milestones and do not
change or restart the GX10 model service. Run the specified tests, then report
the files changed, commands run, test results, and any unresolved decisions.
```

## Status

Milestone 1 (project shell and health page) is implemented: backend and
frontend skeletons, environment-based configuration, `GET /api/health` and
`GET /api/runtime`, and a health page showing portal and upstream state plus
the configured model metadata. Chat, persistence, evaluation suites, and
deployment are still to come (Milestones 2–6).

