# Tasks

Full checks (`uv run scripts/check.py`) are sequenced by the orchestrator: ask before each one, and check `uptime`
first.

## 1. Tests first (spec: config, "Values are checked before a change is recorded")

- [ ] 1.1 In `packages/troupe/tests/test_config_kinds.py`, a test with the issue's script
      (`{"script": {"steps": [{"event": {"type": "init", "runner": "x"}}]}}`): `problems()` names
      `...options.script.steps.0.event.runner` (an object) and `...event.tools` (required), and no problem holds the
      step's description. Verify it fails on main.
- [ ] 1.2 A test with a valid `runner` object and no `tools`: the refusal's problem names `...event.tools` and ends
      with one full stop. Verify it fails on main.
- [ ] 1.3 A test that a step whose event has another `type` (`turn` with no `text`) names that branch's missing field,
      so the `const` discriminator sets the others aside (design D1). Verify it fails on main.
- [ ] 1.4 Fallback tests that pass on main and must keep passing (design D2): a step whose one key no branch defines
      keeps the step's description; Ollama's `think` set to a text outside its list keeps the option's description;
      missing scripted options still name "a script, inline or as a path". The description tests also check the
      problem ends with exactly one full stop (this part fails on main for a description ending in one).
- [ ] 1.5 A test that a key the person put under a map inside a branch is still never shown: a canary key under a
      closest branch's map field doesn't appear in the problem (spec: config, "A refused config value is repeated
      nowhere"). Pick a branch with a map field in the scripted schema, or build a schema in the test if none fits.

## 2. The closest branch (design D1–D4)

- [ ] 2.1 In `packages/troupe/src/troupe/core/config/kinds.py`, expand a `oneOf`/`anyOf` error on an object into the
      one branch left after setting aside branches that fail `additionalProperties` or `type` at the object, or
      `const` at a field directly under it; recurse into nested ones; leave the error as it is otherwise. Feed the
      expanded errors through `_schema_problems`'s existing loop, sorted by path.
- [ ] 2.2 `_rule` drops one trailing full stop from a description.
- [ ] 2.3 Verify 1.1–1.5 pass, and `test_config_kinds.py`, the config CLI tests and the scripted runner's tests pass.
- [ ] 2.4 Run the issue's command in a scratch theatre and paste the new message into the PR description.

## 3. Integration

- [ ] 3.1 Full check (`uv run scripts/check.py`), after asking the orchestrator, and fix anything it finds.
- [ ] 3.2 Draft PR closing #453, act on Claude's review, mark ready once clean.
- [ ] 3.3 Archive the change on the branch before merging.
