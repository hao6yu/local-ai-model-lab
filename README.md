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

## Recommended first prompt for Qwen/OpenCode

```text
Read AGENTS.md and every file under docs/. Implement Milestone 1 from
docs/IMPLEMENTATION_PLAN.md only. Do not implement later milestones and do not
change or restart the GX10 model service. Run the specified tests, then report
the files changed, commands run, test results, and any unresolved decisions.
```

## Status

Planning complete; implementation has not started.

