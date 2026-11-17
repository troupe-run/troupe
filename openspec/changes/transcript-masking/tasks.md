# Tasks

## 1. The failing property test first

- [x] 1.1 Add the record checks (D5), using `masking_checks.py`'s `writings` and `forms_outside_the_marker`: every
  form of the credential outside `[credential]` in a record's text, its JSON writings, and each string it decodes
  to; each JSON value still parses; every value but a replaced one as sent. Verify: they flag today's output for the
  #438 example.
- [x] 1.2 Add the Hypothesis property test (design D5) over generated credentials and JSON records (strings after
  escapes, spans across values, numbers, `data:` lines, multi-line records, text and base64), run through
  `parse_runner_line` and the stored-line path: stored record valid in its shape, no form outside the marker, every
  value outside a replaced one unchanged. Verify: it fails on the current code, and the failure is recorded in the
  commit message.

## 2. Masking a record by its shape

- [x] 2.1 In `masking.py`, classify a record (D1: JSON text, lines of JSON / `data:` JSON / text, or plain text), with
  the cheap gate (a form in some writing, or `\u`). Verify: unit tests for each shape, and that a record no writing of
  which holds a form and without `\u` is returned as the same object.
- [x] 2.2 Mask string and number tokens in place (D2), keeping every other byte. Verify: the #438 example becomes
  `{"text":"key:[credential]"}`; a record with spacing, duplicate keys and a float keeps them byte for byte; a number
  holding an all-digit credential becomes `"[credential]"`; a lone-surrogate escape stays encodable.
- [x] 2.3 Replace the smallest value holding a remaining span, then a line's value, then the whole record (D3).
  Verify: `ab","cd` in `[1,["xab","cdy"],2]` gives `[1,"[credential]",2]`; a span into `data:` keeps the prefix; the
  loop ends on every property-test case.
- [x] 2.4 Add `Masker.record_bytes` for base64 records (D4). Verify: UTF-8 JSON bytes are masked as JSON; non-UTF-8
  bytes and plain text bytes are masked exactly as `Masker.bytes` does.

## 3. The run host

- [x] 3.1 Call `Masker.record` for a text `run/transcript` record in `parse_runner_line` before `Masker.data`, and
  `Masker.record_bytes` in `transcript_record` (D4). Verify: `test_run_host.py` examples for a native Claude Code-style
  line, a kinds `sent` record, a `data:` line, and a base64 record, each stored valid with `[credential]`.
- [x] 3.2 Verify the property test from 1.2 now passes, and the existing masking and run-host tests still pass,
  unchanged (`uv run pytest packages/troupe/tests/test_masking.py packages/troupe/tests/test_run_host.py
  packages/troupe/tests/test_credential_leak.py`).
- [x] 3.3 Time masking a large (≈1 MB) Claude Code-style line with and without the credential, before and after.
  Verify: the numbers are in the PR description, and a line that doesn't hold the credential costs no more than before.

## 4. Specs, docs and the full check

- [x] 4.1 Check the delta specs match what was built (`openspec validate transcript-masking --strict`), and update the
  masking docstrings (`masking.py` module docstring, `framed_record`, the host's mask comment). Verify: validate passes.
- [x] 4.2 Run the full check (`uv run scripts/check.py`, output kept in a scratch file) and one
  `scripts/flake_hunt.py --load 2` over the new property test, when load is under ~40. Verify: both pass.

## Workflow follow-up

- Open the draft PR (`Closes #438`) only after #437 has merged and this branch is rebased onto main.
- Act on Claude's review; archive with `/openspec-archive-change` on the branch before merge.
- After the merge: check #438 is closed and its card says Done.
