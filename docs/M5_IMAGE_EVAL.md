# Milestone 5 design — image evaluation

Vision (image) support layered on top of the text evaluation workflow. Text
workflows are complete; this milestone adds the image workflow on the vision-capable
model only.

## Target model

- Qwen 3.8 supports text, video, and image inputs. This milestone is image (vision).
- Ornith is text-only. Image cases run on Qwen and fail gracefully on Ornith through
  the existing model-mismatch error flow.

## Accepted image formats

- JPEG, PNG, WebP, HEIC/HEIF (`image/heic`, `image/he`, `image/heif`, `heix`), and GIF.
- BMP/AVIF are skipped for the MVP.
- Limit: 10 MiB per file, exactly one image per case.

## Transcoding strategy

- Accept HEIC/HEIF and GIF, then transcode to JPEG on the backend.
- No browser passthrough; the model always receives a standardized JPEG.

## Data URL transport

- The browser encodes the uploaded image as a data URL and sends it to the backend.
- The backend transcodes to JPEG and sends that JPEG as a data URL to the upstream
  OpenAI-compatible `/v1/chat/completions` endpoint.

## Case-type handling

- `input_type` distinguishes text cases from image cases.
- Image cases carry a `case_type`: `transcribe` (exact OCR) or `interpret`
  (inferred meaning). The UI separates exact transcription from inferred interpretation.
- Vision cases are split so the UI separates exact transcription from interpretation.
- Each case is sent independently: text cases use text-only payloads and image cases
  include the image, so text and vision cases can coexist in one run.

## Data flow

- The browser uploads a data URL per image case in the run-request payload.
- On run creation the backend decodes the data URL, detects media type from the bytes,
  validates, and transcodes to a standardized JPEG.
- The validated, transcoded JPEG is stored in the database before any upstream request,
  so invalid media never reaches the model endpoint.
- During execution the stored JPEG data URL is sent to the OpenAI-compatible
  `/v1/chat/completions` endpoint.
- A saved-run preview endpoint serves the stored JPEG bytes to the browser on demand.

## Images in the database

- `evaluation_images` stores one row per image case: `case_id`, `media_type`, `source`
  (`attachment` or `fixture`), the normalized data URL, the JPEG bytes, and `created_at`.
- Rows are child rows of the run (`cascade delete-orphan`), so images are deleted with
  the run and are never stored permanently before a run is created.
- `evaluation_results` carries the preview columns (`image_data`, `image_media_type`,
  `image_source`, `image_data_url`) plus `input_type` and `case_type` for the UI.

## Explicit case-type handling

- Image cases require a vision-capable model (Qwen 3.8). A run is rejected when it selects
  a text-only model (Ornith) for a run that contains image cases.

## Validation rules

- Media type detected from file bytes, not from the filename or Content-Type header.
- Reject unsupported formats and content types.
- Enforce 10 MiB maximum and one-image-per-case.
- Invalid media is rejected before any request is sent upstream, so it never reaches the model.

## Data logging and retention

- Image bytes and data URLs do not appear in normal logs.
- The validation and transcoding paths log only the media type and byte count, never
  the bytes, the raw data URL, or decoded image data.
- Uploaded images are stored with the saved run, not permanently before a run is created.
- Images attached to a run are deleted when that run is deleted.

## Case pairs

- Vision case pair: an image case paired with a transcription case.
- The transcription case carries a known transcription to make output deterministic.

## UI

- The dashboard collects an image per image case (browser upload) before a run is created,
  and rejects a run before it is saved if an image case has no image.
- Image cases show an exact-transcription label (case_type) versus an interpreted
  label, keeping the two apart in the viewer.
- A saved run shows a live preview of each attached image.
- Text cases continue to render prompts, responses, and metrics; image cases render an
  image preview plus text fields.

## Acceptance criteria

- Invalid media never reaches the model endpoint.
- Image bytes and data URLs do not appear in normal logs.
- The UI separates exact transcription from inferred interpretation.
