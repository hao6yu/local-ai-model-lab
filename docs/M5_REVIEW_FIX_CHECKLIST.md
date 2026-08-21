# Milestone 5 review repair checklist

This checklist records the remaining issues found during the post-implementation
review of Milestone 5. Complete every item against the decisions in
`M5_IMAGE_EVAL.md`, add regression coverage, and report anything that remains
incomplete.

## 1. Fix JPEG detection

- Fix JPEG signature detection in `backend/app/image/validation.py`.
- Use a prefix check such as `raw.startswith(b"\xff\xd8\xff")` instead of
  comparing an eight-byte slice to a three-byte marker.
- Add validation and transcoding coverage using a real JPEG generated or loaded
  by Pillow.

## 2. Implement genuine HEIC and HEIF support

- Add and register a decoder such as `pillow-heif`.
- Recognize the common HEIC and HEIF brands expected from real devices.
- Test validation and JPEG transcoding with real HEIC and HEIF fixtures rather
  than synthetic headers.
- Ensure unsupported AVIF and BMP inputs remain rejected for this milestone.

## 3. Fix saved-run image previews

- Fix `getEvaluationImage` in `frontend/src/api/evaluations.ts`.
- The current implementation converts bytes to a binary JavaScript string but
  labels that string as base64 without encoding it.
- Prefer returning a `Blob`/object URL with appropriate cleanup, or correctly
  base64-encode the binary value with `btoa`.
- Add a frontend test proving that JPEG response bytes produce a working image
  source.

## 4. Add a runnable vision evaluation suite

- The shipped U13 vision case is still disabled and lacks the M5 image metadata.
- Add or enable deterministic `transcribe` and `interpret` cases using a real
  fixture.
- Record the known transcription so OCR output can be evaluated repeatably.
- Ensure the shipped portal can run the vision suite without manually editing a
  JSON file first.

## 5. Enforce exactly one attachment per image case

At the backend boundary:

- Reject duplicate attachments with the same `case_id`.
- Reject attachments for unknown case IDs.
- Reject attachments targeting text cases or disabled cases.
- Do not silently discard invalid or extra attachments.
- Continue allowing a suite fixture to satisfy an image case when no upload is
  supplied.
- Add API tests for every accepted and rejected path.

## 6. Derive run modality on the backend

- Do not trust the client-provided `payload.modality` value.
- Derive the stored modality from the immutable loaded suite.
- Use `text`, `image`, or an explicitly documented mixed value consistently.
- Add a direct API test proving an image run cannot be recorded as a text run.

## 7. Enforce suite case invariants

- Require every image case to use `case_type: "transcribe"` or
  `case_type: "interpret"`.
- Remove the undocumented generic `case_type: "image"` value.
- Reject image cases with no case type.
- Reject text cases carrying image fixtures or other image-only metadata.
- Add suite-loader validation tests for these combinations.

## 8. Complete retention behavior

- Add a private endpoint for deleting a saved evaluation run.
- Add a UI action with confirmation before deletion.
- Verify deletion removes the run's `evaluation_images`, copied result-image
  fields, evaluation results, and manual scores.
- Add API/database tests covering the cascade behavior.
- Serve private image previews with `Cache-Control: private, no-store`.

## 9. Expand format, transport, and privacy coverage

Add tests covering:

- Accepted formats: JPEG, PNG, WebP, GIF, HEIC, and HEIF.
- Rejected inputs: corrupt files, BMP, AVIF, empty files, and files over 10 MiB.
- Every accepted source format is normalized before upstream transport.
- The upstream image value always uses `data:image/jpeg;base64,...`.
- Text cases never include an image payload.
- Invalid media is rejected before any upstream request is made.
- Normal application logs contain neither image bytes nor data URLs.

## 10. Update project documentation

- Update the README status through Milestone 5.
- Update `ARCHITECTURE.md` with image persistence, preview/delete endpoints, and
  retention behavior.
- Update `EVALUATION_SUITE.md` and the shipped suite so they no longer describe
  vision as deferred.
- Keep `M5_IMAGE_EVAL.md` as the detailed Milestone 5 contract.

## 11. Format and verify the complete repository

The current repair commit does not pass `ruff format --check`. Format the files
and run the full verification sequence:

```bash
cd backend
ruff format .
pytest
ruff check .
ruff format --check .
mypy
alembic upgrade head
alembic check

cd ../frontend
npm test
npm run typecheck
npm run lint
npm run build
```

## Completion report

Report each checklist item separately, including:

- Files changed.
- Tests added or updated.
- Commands executed and their results.
- Any item that remains incomplete or requires a product decision.

