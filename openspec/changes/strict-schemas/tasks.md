# Tasks

## 1. The strictness check

- [x] 1.1 Add `packages/troupe/tests/protocol_schemas.py`: one registry of every schema in `protocol/schemas/` and
  `plugins/*/schemas/`, registered under their `$id`s (design D4). Make `runner_schemas.py`, `client_schemas.py` and
  `event_schemas.py` delegate to it, keeping their public functions. Verify the existing schema tests pass unchanged
- [x] 1.2 Add the walker (design D1) with its evaluation-context flag, and `test_protocol_strict.py`: one test per
  bad-schema fixture (open object, annotation-only value, `true`, `{}`, map without `propertyNames`, array without
  `items`, an unknown subschema-holding keyword), each asserting the walker reports that fixture at the expected JSON
  Pointer; and one accepting a `oneOf` branch with properties under an enclosing `unevaluatedProperties: false`.
  Verify the fixtures' tests pass
- [x] 1.3 Add the test that runs the walker over every shipped schema, plus the draft 2020-12, `$id`-matches-path and
  references-resolve checks for every file (moving the runner-only versions of those into it). Mark it
  `xfail(strict=True)` with the reason "open fields on main, closed by groups 2 to 6". Verify it xfails, listing
  exactly the fields in design Context and no others (record the list for the PR)

## 2. Runner contract: `native`, `usage`, results and its own error codes

- [x] 2.1 Remove `native` from `runner/run-event.schema.json` and from `troupe.core.runners.protocol`; name the four
  `usage` counters in both (design D7, D8). Verify the runner schema and protocol-type tests, updated for the new
  shapes, pass, and a test that an `init` carrying `native` fails validation and is refused by `from_data`
- [x] 2.2 Remove `native` from the scripted runner's fixtures and recordings, and from `capture_claude.py`'s
  documentation of what is hand-written. Verify `test_claude_fixtures.py`, `test_scripted_fixtures.py` and the
  fixture secret check pass
- [x] 2.3 Close `successResponse.result` as `oneOf` the method results (design D8). Verify schema tests: each
  method's real result validates, and `{"x": 1}` and a `run/start` result with an extra key don't
- [x] 2.4 Add `runner/errors.schema.json` with the contract's seven codes and their details, and make
  `error-response.schema.json`'s `data` `oneOf` those and `{"$dynamicRef": "#runnerErrors"}` with a `false` default
  (design D5). Verify a schema test that a contract error validates and an unpublished code doesn't
- [x] 2.5 Update `docs/runners.md`: no `native` (event table, "not specific to one engine", the Claude Code
  mapping: `system/init` stays in the transcript), the named `usage` counters, the contract's error codes table, and
  a "Publishing a runner's schemas" section (design D3). Verify `test_runners_doc.py`, extended to check the error
  codes table against `runner/errors.schema.json`, passes

## 3. Runner options as an extension point, and the scripted runner's schemas

- [x] 3.1 Make `options` in `runner/run-start.schema.json` and `client/perform-request.schema.json` a `$dynamicRef`
  with a closed default (design D2). Verify schema tests: the contract alone accepts `{}` options and refuses
  `{"script": ...}`; a binding to a test runner schema accepts that runner's options and refuses an unknown key
- [x] 3.2 Add `plugins/runner-scripted/schemas/options.schema.json`, covering every option, step and step field
  `script.py` accepts (design D3), and `schemas/errors.schema.json` for `scripted.invalid-script` and
  `scripted.unknown-option`. Verify plugin tests: every script and recording the plugin ships validates against the
  bound `run/start`; each invalid-script case the existing tests cover also fails the schema; every error the runner
  sends in its tests validates against the bound error-response
- [x] 3.3 Add the conformance check "refuses options holding a key outside its schema" to
  `troupe.core.runners.conformance` (design D3). Verify the conformance suite passes against the scripted runner,
  and fails against a fake runner that ignores unknown option keys
- [x] 3.4 Document the scripted runner's schemas in its README. Verify the README's option list matches the schema's
  properties in a test

## 4. Errors and notices: catalogued codes and closed details

- [x] 4.1 Restructure `error.schema.json` and `notice.schema.json` as common fields plus one `oneOf` branch per
  code under `unevaluatedProperties: false`, with each code's details schema written from its raise sites and keys in
  camelCase (design D5). Verify the walker passes for both files
- [x] 4.2 Rename detail keys to camelCase at every raise site in `packages/` (about 60). Verify `git grep` finds no
  snake_case key in any `details=` mapping, and the existing error and notice tests pass
- [x] 4.3 Add tests that `troupe.core.errors.CODES` and `troupe.core.notices.CODES` list the same codes as their
  schemas, both ways, and that no details schema defines a key with an underscore. Verify each fails on a
  deliberately added code (record the output for the PR)
- [x] 4.4 Add the `protocol_guard` pytest plugin's error and notice hooks and load it for every test path with
  `addopts` (design D4). Verify a test that raising a `TroupeError` with an undeclared detail fails under the guard
  naming the code and the detail, and that the full suite passes
- [x] 4.5 Add the guard's session-end check that every catalogued code was raised (full runs only). Add a test for
  each code it reports unexercised. Verify a full `uv run pytest` passes and a `-k` run skips the check
- [x] 4.6 Update `protocol/README.md` and the error and notice tables in `docs/` to say where each code's details are
  defined. Verify the docs tests that list codes still pass

## 5. Recorded events: a payload schema per topic

- [x] 5.1 Add `protocol/schemas/events/run-started.schema.json`, `run-reported.schema.json` and
  `run-ended.schema.json`, describing what a run records today (design D6). Verify each against payloads from a real
  recorded run (perform with the scripted runner in a test theatre), not hand-written examples
- [x] 5.2 Make `event-record.schema.json` `oneOf` header, troupe event (topic-chosen state) and opaque event; drop
  `troupeEvent`. Verify schema tests: each run topic validates; an unknown topic with inline state doesn't; a
  `state_b64` line still validates; the existing event-record tests, updated, pass
- [x] 5.3 Add the test that `aggregate.TOPICS` and the schema's topics agree both ways. Verify it fails on a
  deliberately added topic (record the output for the PR)
- [x] 5.4 Add the guard's recording hook in troupe's event service (design D4). Verify a test that recording a
  `Run.Reported` with a payload field its schema doesn't define fails under the guard naming the topic, and that the
  store package's recorder-suite tests are unaffected
- [x] 5.5 Document the payload schemas in `docs/event-store.md` and `protocol/README.md`. Verify
  `test_event_store_doc.py` passes

## 6. Integration

- [x] 6.1 Remove the `xfail` from the strictness test (1.3). Verify it passes over every shipped schema, and that
  re-adding `"type": "object"` to any one field makes it fail naming that field
- [ ] 6.2 Run `uv run scripts/check.py` (ruff, format, mypy --strict, import-linter, the full suite). Verify it passes
  locally and on CI on Linux, macOS and Windows

## Workflow follow-up

- Open the PR with `Closes #70`; archive the change on the branch before merging; after the merge, comment on #70.
- #60 (config model) is then unblocked. Its design reuses D2's extension points for actor files and decides run-time
  validation and the type generator.
