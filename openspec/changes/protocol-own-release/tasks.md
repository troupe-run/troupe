# Tasks

## 1. The protocol releases on its own (design D1, D2, D3; spec: releases)

- [x] 1.1 In `scripts/tests/workspace/test_release_config.py`, replace the two tests that assert the old rules
  (`test_the_protocol_left_out_of_the_linked_group_is_named`, `test_a_protocol_entry_with_a_lock_update_is_named`)
  with known-bad tests for D3: protocol in the linked group; the protocol entry without the `version.json` extra-file,
  or with a different one; `version.json` missing, not an object, with an extra key, and with a version differing
  from the manifest's. Each asserts the exact message, naming the file(s) and the fix. Verify they **fail** against
  the current `release_config.py` and config (run `uv run pytest scripts/tests/workspace/test_release_config.py`)
- [x] 1.2 Add `packages/troupe/src/troupe/protocol/version.json` (`{"version": "0.0.0"}`, ending in a newline), remove
  `protocol` from the linked group's `components` and add D2's `extra-files` entry to the protocol in
  `release-please-config.json`. Change `_protocol_problems` and `_group_problems` in `scripts/release_config.py` to
  D3, and update its docstrings (`LINKED_GROUP`, `PROTOCOL`). Verify 1.1's tests and
  `test_every_workspace_member_is_configured_for_release` pass
- [x] 1.3 Add a test to `packages/troupe/tests/test_schemas.py` that `scripts/package_schemas.py`'s write leaves
  `version.json` in the copy untouched (D2), and that `--check` doesn't report it. Verify it passes, and fails when
  `PATTERN` is widened to `*.json` locally
- [x] 1.4 Update `contributing/releasing.md` (the protocol as its own component, its tags, that a protocol release
  rewrites `version.json`, and that a schema change is `feat`/`fix`/breaking, never another type) and
  `docs/backstage/changelog.md` (the protocol under its own heading, not in the linked group). Verify the user-docs
  tests pass (`uv run pytest packages/troupe/tests/test_user_docs_changelog.py packages/troupe/tests/test_user_docs_links.py`)
- [x] 1.5 Check release-please's view of the new config: run release-please's `release-pr --dry-run` against this
  branch if a token allows it, or otherwise validate `release-please-config.json` against the `$schema` it names.
  Record which was run, and its result, in the commit message

## 2. Core reads the recorded version (design D4; spec: protocol)

- [x] 2.1 Add `schemas.protocol-version-invalid` to `protocol/schemas/error.schema.json` with its `details` schema,
  regenerate the copy (`uv run scripts/package_schemas.py`), and add the code to core's catalogue in
  `core/errors.py`. Verify `test_protocol_strict.py` and the catalogue-agreement tests pass
- [x] 2.2 Write tests first in `packages/troupe/tests/test_schemas.py`: the packaged record reads as `0.0.0` (equal to
  the manifest's protocol version); a record of `"next"`, `"1.2"`, `"01.2.3"`, a non-object, an extra key, and a
  missing file are each refused with `schemas.protocol-version-invalid` naming the file; `protocol_major()` of
  `1.3.0` is `1`. Use a temporary directory for the bad records. Then add `protocol_version()` and `protocol_major()`
  to `core/schemas.py` and update its module docstring. Verify the tests pass and `uv run mypy --strict` is clean
- [x] 2.3 No test builds a wheel today. Add one (spec: protocol, "An installed troupe"): `uv build --package troupe
  --wheel` into a temporary directory, then assert the wheel holds `troupe/protocol/version.json` with the recorded
  version and every `*.schema.json` in the copy. If the build is too slow for the core suite (over ~10 s), put it in
  the scripts suite and say so in the commit. Verify it passes, and fails when `version.json` is excluded
- [x] 2.4 Add a "Versions" section to `protocol/README.md`: the protocol's own releases and `protocol-v*` tags, the
  site's `troupe.run/protocol/<version>/` and major-version paths (troupe-run/website#30), where troupe records the
  version it ships, and that a checkout between releases records the last release. Verify the docs link tests pass

## 3. Every surface reports it from there (design D5, D6, D7; specs: event-store, cli, config-files)

- [ ] 3.1 Segment header (D5), tests first: in `packages/troupe-store-text/tests/test_codec.py` and
  `test_segments.py`, a written header carries `"protocol"` equal to `protocol_version()`; a header without it, or
  with `"next"`, is refused as `events.malformed-record` naming file and line; in
  `packages/troupe/tests/test_event_schemas.py`, a header without `protocol` doesn't validate. Update every
  hand-written header fixture to carry `protocol`. Then change `event-record.schema.json` (with `$defs/protocolVersion`
  and its description), regenerate the copy, and change `Header`, `encode_header`, `_header` and `TextStore`'s
  header write. Verify `uv run pytest packages/troupe-store-text packages/troupe/tests/test_event_schemas.py` passes
- [ ] 3.2 Update `contributing/event-store.md`'s header example and its description of the header's fields, and the
  README's `event-record.schema.json` row. Verify `test_event_store_doc.py` passes
- [ ] 3.3 `--version` (D6), tests first in `packages/troupe/tests/test_cli.py`: outside a theatre it prints
  `troupe <version> (protocol <recorded version>)` and exits 0; with a broken record (monkeypatched location) it
  renders `schemas.protocol-version-invalid` and exits with that code's exit code. Then change `cli/__init__.py`, and
  `docs/prompt-book/cli.md` wherever it shows or describes the output. Verify the CLI tests and `test_cli_docs.py` pass
- [ ] 3.4 `$schema` URL (D7), tests first in `packages/troupe/tests/test_config_files.py`: with the packaged record
  the written actor file's bytes are unchanged (`/protocol/0/`); with a record of `1.3.0` (monkeypatched) both the
  comment and the key name `/protocol/1/`. Then replace `ACTOR_SCHEMA_URL` with `actor_schema_url()` in
  `core/config/kinds.py`, use it in `projection.py`, and check `cli/values.py` for the same constant. Verify the config
  tests pass, including the existing hash and flush tests unchanged

## 4. Integration

- [ ] 4.1 Run `uv run scripts/check.py` and see it pass. Then, in a scratch theatre, run `troupe --version`, record an
  event and read the new segment's first line, and confirm it carries the recorded protocol version
- [ ] 4.2 Open a follow-up issue in troupe-run/infrastructure for a guard rule that refuses a non-releasable commit
  type changing `protocol/schemas/` (design, Risks), on the roadmap board (`--project "troupe roadmap"`), and link it
  from the PR. Verify with `gh issue view <n> -R troupe-run/infrastructure --json projectItems`

## Workflow follow-up

- Open the PR with `Closes #140`, and note the breaking segment-header change in its body.
- Run `/opsx:archive` on the branch before merging.
- After the merge, comment on #140 with the PR and the archived change, and check the card says Done.
