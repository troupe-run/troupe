# Proposal

## Why

`openspec validate --specs --strict` fails on main (#155). Two requirements have descriptions over OpenSpec's
500-character limit: `runner-protocol`'s "Run start carries everything the runner may use" (544) and
`scripted-runner`'s "A script is a list of steps played in order" (633). Without `--strict` the limit is only a
warning, but a strict run over every spec can't pass while they stand. So a strict run hides any new failure in those
two specs, and makes a change that touches other specs look as if it broke something. It was found while archiving
#51.

Each of the two descriptions states several behaviours. OpenSpec's guidance is to split such a requirement into
requirements that each state one behaviour, in a change made for that purpose.

## What Changes

Each original keeps its header and every scenario, as OpenSpec's guidance asks. Each added requirement gets its own
scenarios.

- **`runner-protocol`: "Run start carries everything the runner may use" is split into three requirements.**
  - The original's description keeps only what `run/start` carries.
  - **Added: "The runner takes direction, character and configuration only from its run start."** This is the
    sentence "the runner SHALL use no other source …", which no scenario covered. Its scenario checks troupe's side:
    the runner's command line and environment don't hold the direction, the character or the options.
  - **Added: "Run start options are an extension point."** This is the sentence about the options' schema. Its
    scenario is the one `test_the_contract_alone_accepts_only_empty_options` already checks, which no scenario named.
- **`scripted-runner`: "A script is a list of steps played in order" is split into three requirements.**
  - The original's description keeps where the script comes from and that its steps play in order.
  - **Added: "A script's steps cover what a runner can send or do."** This is the list of step kinds. Its scenario
    checks that the published options schema defines each kind the list names. The schema also defines `replay`
    and `checkCharacter`, which other requirements cover. The list says "cover", not "only", so this is no conflict
    (design D3).
  - **Added: "Steps that don't wait play without reading troupe's messages."** This is the rest of the description.
    Its scenarios are the two waits no test covered: a message answered during a `wait` step, and during a replay's
    delays.
- **No behaviour changes.** Every sentence of the two descriptions survives, in the original or in an added
  requirement, with its meaning unchanged. The new scenarios describe behaviour the code already has, and their tests
  pass on main before any spec edit.
- **Each test's `# Requirement:` comment names the requirement its tests cover.** The comments that name a
  requirement and a sub-behaviour in brackets, such as "(options are an extension point)", are split so each test
  sits under the requirement whose scenario it checks.
- **`openspec validate --specs --strict` passes**, and so does `openspec validate split-long-requirements --strict`.

Not in this change: a gate that runs strict validation so this can't come back. `scripts/check.py` is the wrong home
for it. The `quality-check` requirement "No gate reads OpenSpec artifacts" forbids it, and `check-paths.toml` skips
the check for commits that touch only `openspec/**`, which are the commits that could break validation. Where it
should run instead (the guard in `troupe-run/infrastructure`, or a CI job here) is a question for the owner. It goes
to a follow-up issue (design, Open Questions).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runner-protocol`: "Run start carries everything the runner may use" is cut to one behaviour, and two requirements
  are added for the behaviours removed from it.
- `scripted-runner`: "A script is a list of steps played in order" is cut to one behaviour, and two requirements are
  added for the behaviours removed from it.

## Impact

- `openspec/specs/runner-protocol/spec.md` and `openspec/specs/scripted-runner/spec.md`, through the archive.
- Tests: the `# Requirement:` comments in `packages/troupe/tests/test_runner_schemas.py`,
  `packages/troupe/tests/test_run_host.py` and `plugins/runner-scripted/tests/test_scripted_runner.py`. New tests for
  the added scenarios: one in `test_run_host.py`, two in `test_scripted_runner.py`
  and one in `plugins/runner-scripted/tests/test_scripted_schemas.py`.
- No production code, protocol schema, docs or CLI output changes.
