# Product Specification

## Purpose

Local AI Model Lab answers a practical question: which locally hosted model/profile is most useful for daily chat, documentation, vision, and low-priority coding on the GX10?

It should replace subjective one-off testing with repeatable saved evaluations while remaining useful as a simple daily chat interface.

## Primary user

The initial release is single-user. Family access may be considered later, but authentication and multi-user history are not MVP requirements.

## Goals

1. Make any configured GX10 model easy to select and test from a browser.
2. Produce repeatable measurements with identical prompts and settings.
3. Make official-versus-uncensored comparisons easy to inspect.
4. Preserve enough metadata to understand why two runs differ.
5. Keep the portal private, lightweight, and independent of the inference runtime.

## Non-goals for the MVP

- Starting, stopping, downloading, loading, or reconfiguring model containers.
- Concurrent generation from multiple configured models in normal portal use.
- Autonomous coding-agent tools, shell execution, repository editing, or sub-agents.
- Public accounts, billing, cloud synchronization, or internet exposure.
- Training, fine-tuning, quantizing, or modifying model weights.
- Automatic claims that one answer is objectively better.
- Web search or browser control.
- Image or video generation.

## Core concepts

### Endpoint

An OpenAI-compatible inference server. The retained GX10 deployment uses
SGLang at `http://127.0.0.1:30000` for Ornith and `http://127.0.0.1:30001` for
Qwen. The isolated DeepSeek experiment uses vLLM/SparkInfer at
`http://127.0.0.1:8888` on the GX10 and a Mac-only tunnel on port 30002. These
addresses remain private to the backend. DeepSeek runs exclusively; it is not
resident beside Ornith and Qwen.

### Model profile

A human-readable snapshot of the loaded model configuration, for example:

- official Qwen3.8-27B NVFP4 + optimized DSpark
- community uncensored Qwen3.8-27B NVFP4 + optimized DSpark
- community Qwen3.8-27B uncensored NVFP4 + DFlash2 daily profile
- OrcaRouter Qwen3.8-27B uncensored NVFP4 + DFlash2 compatibility profile
- DeepSeek V4 Flash 0731 EXL3 3.0 bpw + DSpark K5

The portal records the profile label supplied by configuration or entered before an evaluation. It does not infer quantization or speculative-decoding settings from the generic API model ID.

### Test case

A versioned prompt with a category, input type, optional expected properties, and scoring guidance.

### Evaluation run

One execution of a versioned test suite against one recorded model profile using one settings snapshot.

### Result

The response and measured metadata for one test case within an evaluation run.

## MVP user flows

### Chat playground

1. Open the portal.
2. Confirm endpoint health and select DeepSeek, Ornith, or Qwen.
3. Select a supported reasoning mode and output-token limit.
4. Send a message and see streamed output.
5. Start a new conversation or clear local history. Switching models starts a
   new conversation so one transcript never silently mixes models.

### Evaluation run

1. Select a test suite.
2. Confirm the current model profile label and settings.
3. Start the run.
4. Observe progress one test case at a time.
5. Review outputs and measured performance.
6. Give each response manual scores and notes.

### Sequential A/B comparison

1. Complete and save a run with profile A.
2. Select the other configured model endpoint.
3. Complete the same suite and version with profile B.
4. Select the two saved runs.
5. Compare prompts, answers, timing, throughput, scores, and notes side by side.

## Required settings recorded per run

- Profile label
- API model ID returned/configured
- Suite name and immutable suite version
- Date and application version
- Reasoning mode
- Temperature
- Maximum completion tokens
- Context-window declaration
- Input modality
- Any user-entered runtime notes

## Required measurements

- Request start timestamp
- Time to first streamed content
- Total completion time
- Prompt tokens, when reported by the server
- Completion tokens, when reported by the server
- Generation tokens per second, clearly marked as server-reported or calculated
- Finish reason
- HTTP/upstream error details suitable for the user

Reasoning tokens and visible tokens must not be presented as separate measured values unless the upstream server actually reports them separately.

## Manual scoring

Each result can receive a score from 0 to 2 for:

- Accuracy
- Completeness
- Instruction following
- Appropriate judgment

It also supports a free-form note and flags for refusal, suspected hallucination, truncation, and unsafe output. The application must not assign these subjective scores automatically in the MVP.

## Vision requirements

Vision support is introduced after the text workflow works. Initial limits:

- JPEG, PNG, or WebP only
- 10 MiB maximum per file
- One image per test case
- Data URL transport to the upstream OpenAI-compatible API
- No permanent storage unless the user explicitly saves the attachment

Video testing is deferred. A future version may extract controlled frame samples, but must not pretend the text model generates video.

## UX requirements

- Desktop-first but usable on a phone over Tailscale.
- Dark and light themes may follow the operating-system preference.
- Streaming must remain readable without jumping the page unexpectedly.
- Long responses should not be silently truncated by the portal.
- Metrics must distinguish TTFT from generation speed.
- Experimental profiles must be visibly labeled.
- Errors should explain whether the portal, network, or model endpoint failed.

## Success criteria

The initial product is successful when the same suite can be run on the official and community uncensored profiles on different occasions, both runs remain saved, and the user can make an evidence-based comparison without copying results into another document.
