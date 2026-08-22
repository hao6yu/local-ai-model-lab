# Local AI Model Lab

A private web portal for testing local language models on the ASUS Ascent GX10. The current targets are DeepSeek V4 Flash, Ornith, and Qwen. Ornith and Qwen are the active dual-resident deployment with 262K context ceilings; DeepSeek is the retained exclusive full-memory text profile.

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

## Deployment (GX10 + Tailscale)

The production portal is a single process that serves both the API and the built
React SPA on loopback (`127.0.0.1:8081`), fronted by Tailscale Serve so only
tailnet devices reach it. The inference endpoints stay loopback-only and are
never exposed.

1. **Install** on the GX10 from a checkout of this repo:
   ```bash
   cd /path/to/repo
   sudo ./deploy/gx10/install.sh
   ```
   It creates a venv, builds the frontend, installs a systemd service
   (`ai-model-lab`), and starts it on `127.0.0.1:8081`. Then edit
   `/opt/local-ai-model-lab/backend/.env` with the inference endpoints.
2. **Expose over the tailnet** (Funnel stays off):
   ```bash
   PORTAL_DOMAIN=my-gx10.ts.net sudo ./deploy/gx10/tailscale-serve.sh
   ```
   Without `PORTAL_DOMAIN`, a `.ts.net` subdomain is assigned automatically.
3. **Health after reboot** runs 2 minutes after boot, then every 10 minutes:
   ```bash
   systemctl status health.timer
   journalctl -u health.service -f
   ```
4. **Back up / restore** the SQLite database:
   ```bash
   ./deploy/gx10/backup-sqlite.sh                 # -> data/backups/model-lab-*.db.gz
   sudo ./deploy/gx10/restore-sqlite.sh data/backups/model-lab-20250801-120000.db.gz
   ```

See `deploy/gx10/` for the service unit, install script, Tailscale helper, and
backup/restore scripts.

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
freezing the interface. Milestone 3 (evaluation suites and saved runs) is now
implemented end-to-end from the browser: create a run, stream results, score
results, save scores, list saved runs, and reload a saved run from the
database. Persistence is defined by the ORM schema, so the app works without
migrations and still creates its own schema at startup via
`Base.metadata.create_all`. The alembic migration scripts now match the schema:
a clean database upgrades through `1_initial` and
`2_suite_snapshot_and_format_failure`, and an existing M3 database upgrades to
the current schema with `alembic upgrade head` (SQLite-only). The GX10 and
Tailscale deployment (Milestone 6) is described in `docs/IMPLEMENTATION_PLAN.md`.

Milestone 4 adds serialized A/B comparison between saved runs. The user
selects two finished runs from the same suite name, version, and cases, and
the portal renders them side by side. Compatible runs are matched by `case_id`
rather than array position, so runs from different models (for example Ornith
and Qwen) can be compared even though they were executed at different times.
Each case shows the shared prompt, both responses, timing and throughput
metrics, per-result scores, refusal/hallucination and other flags, and manual
notes. A run that is not finished (still created or running), or whose case
prompts do not match, is rejected with a descriptive error instead of a generic
one. The comparison can
be exported to Markdown (including the prompt, notes, and flags) or to
machine-readable JSON. A single active evaluation run is preserved so
comparison results stay consistent while another run executes.

Milestone 5 adds the image/vision evaluation path. The server validates every
upload at the backend boundary (format signature, `image/jpeg`, and a 10 MiB
limit), trans-codes accepted formats such as JPEG, PNG, WebP, GIF, HEIC, and
HEIF to a single JPEG, and stores the bytes in SQLite so previews never round
trip through the browser. Text cases never carry an image payload, and the
upstream model adapter receives only the transcoded data URL. A private
`DELETE /api/evaluation-runs/{id}` endpoint removes a finished run together with
its images, results, and scores, and private image previews use
`Cache-Control: private, no-store`. The shipped suite now runs a real vision
case (U13 — transcribe every visible word in `data/suites/fixtures/u13-
transcription.png`) against a known transcription, so OCR output can be evaluated
repeatably. The shipped suite also runs a runnable interpretation case (U13B —
infer meaning from `data/suites/fixtures/u14-interpretation.png`), which bumps
the suite to version 2 and records mixed text-and-image runs as modality `mixed`.

Milestone 5's post-implementation review findings are addressed: generic HEIF
(`mif1`) files are detected and decoded, duplicate suite case ids are rejected
at load time, a duplicate `(run_id, case_id)` pair is enforced in the database,
an invalid suite produces a controlled 400 instead of a 500, resetting an
evaluation clears the suite selection, and deleted runs are restricted to
finished runs. See `docs/M5_FINAL_REVIEW_FINDINGS.md`.

Milestone 6 delivers the GX10 and Tailscale deployment. The portal is a
self-contained process serving the built React SPA and the API on loopback
(`127.0.0.1:8081`); the inference endpoints stay loopback-only. A systemd unit
(`deploy/gx10/ai-model-lab.service`) runs it behind Tailscale Serve, with Funnel
disabled so only tailnet devices can reach it. A systemd timer plus a stdlib-only
health probe verify the portal and its upstream model after reboot. A SQLite
backup/restore pair protects the saved runs. The reproducible install script
(`deploy/gx10/install.sh`) creates a venv, builds the frontend, installs the
units, and starts the service. See `deploy/gx10/`.
