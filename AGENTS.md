# Agent Instructions

These instructions apply to the entire repository.

## Product boundary

Build a private evaluation portal for an existing OpenAI-compatible model endpoint. Do not turn this repository into a model installer, model manager, general autonomous agent, or public SaaS application.

The model is hosted separately by SGLang on the GX10. Never start, stop, replace, download, or reconfigure a model unless the user explicitly asks for that separate operation.

## Required workflow

1. Read `README.md` and all files under `docs/` before changing code.
2. Work on only the requested milestone.
3. Inspect existing files before editing them.
4. Prefer the smallest implementation that satisfies the documented acceptance criteria.
5. Add or update automated tests for behavior changed.
6. Run relevant formatting, type checks, and tests before reporting completion.
7. Report exactly what changed, what was tested, and what remains incomplete.

If documentation conflicts, use this priority order:

1. The user's current request
2. `AGENTS.md`
3. `docs/PRODUCT_SPEC.md`
4. `docs/ARCHITECTURE.md`
5. `docs/IMPLEMENTATION_PLAN.md`

Do not silently change a documented product decision. Record proposed changes in the final report and wait for approval.

## Safety and privacy

- Bind development services to `127.0.0.1` by default.
- Do not enable Tailscale Funnel or expose the portal to the public internet.
- Never commit API keys, Tailscale credentials, SSH keys, chat history, uploaded media, or `.env` files.
- Treat prompts, responses, and attachments as private local data.
- Store uploaded media only when a user explicitly chooses to retain it.
- Do not log complete prompts, responses, authorization headers, or image data in normal application logs.
- Reject unsupported file types and enforce documented upload-size limits.
- The browser must never receive the upstream model endpoint or credentials.

## Model integration

- Use the OpenAI-compatible `/v1/chat/completions` API.
- Preserve streaming from the upstream endpoint to the browser.
- Obtain endpoint, model ID, and optional key from environment variables.
- Do not hard-code Mac hostnames, GX10 addresses, Tailscale names, or secrets.
- Assume only one model profile is active at a time.
- A request failure must produce a useful error without destroying the saved run.
- The server must impose a single active evaluation run for the MVP; normal interactive chat may also be serialized initially.

## Code quality

- Keep backend and frontend types explicit.
- Validate all external input at the backend boundary.
- Use database migrations once persistent tables exist.
- Keep model-provider code behind a small adapter so another OpenAI-compatible server can be added later.
- Avoid speculative abstractions and dependencies that are not needed by the current milestone.
- Do not claim a metric that was not measured. Clearly distinguish server-reported token counts from locally estimated counts.

## Definition of done

A milestone is complete only when its acceptance criteria pass, automated tests pass, documentation reflects any intentional change, and the app can be started using documented commands on a clean development environment.

