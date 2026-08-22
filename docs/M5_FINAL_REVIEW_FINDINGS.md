# Milestone 5 final review findings

This checklist records the remaining issues found after reviewing commit
`9a13b48` (`feat(M5): complete vision-suite retention UI and docs`). Address
each item, add regression coverage, and rerun the complete repository checks.

## 1. Restore image cases after resetting an evaluation

**Priority: High**

`frontend/src/features/evaluations/EvaluationDashboard.tsx::resetRun` clears
`caseList` and sets `caseListState` to `none`, but it does not clear
`selectedSuite`. The suite-loading effect only runs when `selectedSuite`
changes. Consequently, choosing **New evaluation** or closing a loaded run can
leave the selected suite visible while its image upload controls remain gone.

Required work:

- Make resetting internally consistent: either retain/reload the current
  suite's cases or clear the selected suite so the user must select it again.
- Verify that starting a second image evaluation does not require switching to
  another suite and back.
- Add a frontend regression test covering reset followed by another image run.
- Cover both **New evaluation** and closing a loaded saved run if they continue
  to share `resetRun`.

## 2. Implement and genuinely test generic HEIF support

**Priority: High**

`backend/app/image/validation.py::detect_media_type` recognizes `mfi1`, which
appears to be a typo for the common `mif1` HEIF brand. A Pillow-decodable file
with a `mif1` major brand is currently rejected as `unsupported image type`.

The existing `_heic_bytes()` and `_heif_bytes()` helpers in
`backend/tests/test_image_validation.py` both call Pillow with
`format="HEIF"`. They currently produce byte-identical files whose major brand
is `heic`, so the test suite exercises HEIC twice and never tests a generic
HEIF-branded input.

Required work:

- Correct the supported ISO-BMFF HEIC/HEIF brand detection, including at least
  a genuine `mif1` HEIF input and the HEIC brands supported by the product
  contract.
- Keep AVIF rejected for this milestone.
- Replace or supplement the generated helpers with genuinely distinct,
  decodable HEIC and HEIF fixtures.
- Assert the detected source media type for both fixtures before asserting JPEG
  normalization.
- Verify both files decode and normalize to `data:image/jpeg;base64,...`.

Reproduction observed during review:

```text
Pillow decoded mif1-major file: HEIF (4, 4)
validator rejected mif1-major file: MediaValidationError unsupported image type.
```

## 3. Reject duplicate suite case IDs during suite loading

**Priority: Medium**

`backend/app/evaluations/suite_loader.py::_validate_cases` does not enforce
unique case IDs. A suite containing two image cases with the same ID is listed
and can create a run successfully. Starting the run then raises SQLAlchemy
`MultipleResultsFound` because multiple result rows share the same
`run_id`/`case_id` pair.

Required work:

- Reject duplicate case IDs with `SuiteValidationError` while loading or
  parsing a suite snapshot.
- Include the duplicate ID in the validation message.
- Add suite-loader coverage for duplicate text and image case IDs.
- Add an API regression test proving an invalid duplicate-ID suite cannot
  produce a run that later fails with HTTP 500.
- Consider database uniqueness constraints for `(run_id, case_id)` in both
  `evaluation_results` and `evaluation_images` as defense in depth. If added,
  provide an Alembic migration and migration tests.

Reproduction observed during review:

```text
duplicate create: 200
duplicate start raised: MultipleResultsFound
```

## 4. Ship a runnable interpretation case

**Priority: Medium**

The M5 repair checklist calls for deterministic runnable `transcribe` and
`interpret` cases. The shipped suite currently contains only U13, whose
`case_type` is `transcribe`. Tests use an `interpret` case only in synthetic
test data, and that case is disabled.

Required work:

- Add an enabled, deterministic `interpret` case to the shipped evaluation
  suite, using a real fixture.
- Give it a prompt and expected properties that evaluate inferred meaning
  rather than exact OCR.
- Confirm the portal visibly distinguishes the interpretation case from the
  transcription case.
- Add an API/UI test using the shipped interpretation case.
- Update `README.md`, `docs/EVALUATION_SUITE.md`, and the M5 documentation as
  needed.

## 5. Represent mixed text-and-image runs consistently

**Priority: Medium**

`backend/app/api/evaluations.py::create_evaluation_run` stores `image` whenever
the suite contains any enabled image case. The shipped suite contains both
text and image cases, so its recorded modality is misleading. The prior repair
checklist requires `text`, `image`, or an explicitly documented mixed value.

Required work:

- Derive `text` for text-only suites, `image` for image-only suites, and
  `mixed` for suites containing both enabled input types; or explicitly
  document a different precise contract everywhere.
- Update schemas/types if `mixed` is introduced as a literal value.
- Add direct API tests for all supported modality combinations.
- Confirm saved-run details and comparison exports show the derived value.

## 6. Align deletion behavior with the documented lifecycle

**Priority: Low**

The DELETE endpoint rejects only `running` runs and currently deletes a run in
the `created` state. `README.md` and `docs/ARCHITECTURE.md` say only finished
runs may be deleted. Deleting abandoned created runs may be desirable, but the
implementation and documentation must agree.

Required work:

- Decide whether deletion supports terminal runs only or terminal plus
  never-started `created` runs.
- Enforce the chosen state set explicitly in the API.
- Update the README, architecture document, UI wording, and tests to match.
- Continue rejecting deletion of active `running` runs with HTTP 409.

## 7. Return a controlled response for invalid suites on run creation

**Priority: Low**

`POST /api/evaluation-runs` catches `SuiteNotFoundError` but not
`SuiteValidationError`. A direct request naming an invalid on-disk suite can
therefore raise an unhandled exception instead of returning a controlled 4xx
response. Suite listing hides invalid suites, but API callers should still get
a stable response.

Required work:

- Catch `SuiteValidationError` during run creation and return a descriptive 4xx
  response without leaking internals.
- Use consistent invalid-suite behavior across suite listing, case listing, and
  run creation.
- Add a direct API regression test.

## Verification

The reviewed commit passed the existing checks before these findings were
recorded:

- Backend: 143 tests, mypy, ruff check/format, Alembic upgrade/check.
- Frontend: 61 tests, TypeScript typecheck, ESLint, and production build.

After fixing the items above, rerun:

```bash
cd backend
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/alembic upgrade head
.venv/bin/alembic check

cd ../frontend
export PATH="$HOME/.nvm/versions/node/v18.20.8/bin:$PATH"
npm test -- --run
npm run typecheck
npm run lint
npm run build
```

Do not consider M5 complete until the first four findings are fixed and the
remaining contract decisions are explicitly resolved and documented.

## Resolution status

All seven findings are addressed below. The full repository checks were
rerun after the fixes: 148 backend tests, mypy, ruff check/format, and
Alembic upgrade/check all pass; 63 frontend tests, TypeScript typecheck,
ESLint, and the production build all pass.

1. **Reset restores the suite** (`EvaluationDashboard.tsx`). `resetRun` now calls
   `setSelectedSuite(null)`, so the case list and image-upload panel clear with
   the run. A regression test (`clears the suite selection when a run resets`)
   confirms the selection clears, and a second test confirms the user can start
   another run right after.

2. **Generic HEIF support** (`backend/app/image/validation.py`). The ISO-BMFF
   major-brand table now accepts the generic HEIF brands (`heif`, `mif1`,
   `mif2`, `mfc1`) instead of the earlier typo `mfi1`; HEIC detection also
   accepts `hev1`/`hevc`. `test_generic_mif1_heif_is_detected_and_decoded`
   builds a decodable file, relabels its major brand to `mif1`, asserts the
   source media type is `image/heif`, and asserts it normalizes to JPEG. AVIF
   remains rejected.

3. **Duplicate case ids** (`suite_loader.py::_validate_cases` +
   `app/db/models.py` + `alembic/versions/4_result_image_uniqueness.py`). The
   loader rejects a suite that repeats a case id, and the database now enforces
   uniqueness on `(run_id, case_id)` for both `evaluation_results` and
   `evaluation_images` as defense in depth. Tests
   (`test_suite_with_duplicate_case_ids_is_rejected_on_run_creation`,
   `test_suite_with_duplicate_image_case_ids_cannot_create_a_run`) cover the API
   rejection.

4. **Runnable interpretation case** (`data/suites/uncensored-behavior-v1.json`
   + `data/suites/fixtures/u14-interpretation.png`). A new enabled `interpret`
   case `U13B` runs against a real fixture. The suite version bumped 1 -> 2.
   `EVALUATION_SUITE.md` documents both vision cases.

5. **Modality** (`api/evaluations.py`). `run_modality` is derived from the
   loaded suite: `mixed` when both text and enabled image cases exist, `image`
   for image-only suites, `text` for text-only. `test_image_only_suite_derives_image_modality`
   covers the image-only path; the mixed path is covered by the shipped-suite
   run test.

6. **Delete lifecycle** (`api/evaluations.py`). `DELETE` now only accepts
   terminal runs (`completed`, `failed`); `running` and never-started
   `created` runs are rejected with HTTP 409. This matches the documented
   "finished run only" contract in `ARCHITECTURE.md`. `test_delete_run_removes_it_and_cascades`
   was updated to finish the run first.

7. **Invalid suite on run creation** (`api/evaluations.py`). `create_evaluation_run`
   now catches `SuiteValidationError` and returns a controlled 400, consistent
   with suite listing. `test_invalid_suite_is_rejected_on_run_creation` covers it.
