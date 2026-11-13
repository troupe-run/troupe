# Design

## Context

See proposal.md for why. #263 is release-please's pull request `chore: release main` at 21060ecc. It first releases
`troupe-plugin-sdk`, `troupe-runner-lm-studio`, `troupe-runner-ollama` and `troupe-runner-openai` at 0.1.0, and moves
core, three adapters, two runners and the protocol to 0.2.0. A copy of that branch (`git archive`, its own `uv sync`)
fails the same 19 tests locally as on CI ([run 43399238032](https://github.com/troupe-run/troupe/actions/runs/43399238032)).
The failures fall into three groups:

| Tests | Cause | Kind |
|---|---|---|
| 11 × `test_replaying_a_fixture_gives_exactly_its_records_and_events` (Ollama) | `events.json` holds `init`'s `runner.version` `0.0.0` | test |
| 7 in `test_bundle.py` / `test_release_config.py` | they write or expect `troupe-runner-lm-studio` bare, or assume the SDK is unreleased | test |
| `test_troupe_run_installs_troupe_with_every_workspace_member` | `bundle.py`'s pinned-dependency rule (runner-sdk D12) fails on the real files | check |

The release pull request is only ever written by the release App (contributing/releasing.md), so the fix has to come
through `main`, and release-please then rebuilds #263.

## Goals / Non-Goals

**Goals:**

- Every test that copies or replays repository state passes on `main`, in #263's state, and in the state the pinning
  pull request after #263 leaves (every first-released member pinned, the exclusion removed).
- A `troupe-run` tag still never names a needed workspace member bare.

**Non-Goals:**

- Changing release-please's configuration, `pin_bundle.py` or the release workflow. They did what #262 and the
  releases spec say.
- #274's checks after the release. This change only unblocks its first step.

## Decisions

### D1. Ollama's replay compares the runner version as `<package version>`

`fixture_replay.replay` checks each `init` event's `runner.version` against
`importlib.metadata.version("troupe-runner-ollama")`, then replaces it with `<package version>`. Each fixture's
`events.json` holds `<package version>`. This is exactly what `openai_fixture_replay.py` does, so the two plugins
read alike. `write_recorded`, which writes a hand-written fixture's events, goes through `replay` and so writes the
placeholder too. The capture tool (`tools/capture_ollama.py`) writes the placeholder into `init` as well, so a fixture
captured after a release still replays, and its test checks it does.

*Alternative:* write the version into the fixtures at release time. Rejected, because only the release App writes the
release branch, and the fixture would then record a version the capture never saw.

The check against the installed version keeps what the fixture test showed before: the runner reports its own
package's version, not a constant.

### D2. Workspace tests keep the copy's real extras, whatever they hold

The tests that keep "the real `lm-studio` extra" (`with_lm_studio`, `set_extras` calls with `[LM_STUDIO]`, and
`test_the_bundle_has_the_lm_studio_extra_and_all_naming_it`) stop naming LM Studio. They read the extras the copy's
bundle holds (each runner's requirement, bare or pinned as the copy has it, and `all`) and keep them as they are
beside the fixture runner `example`, which stands for a library-backed runner in an extra. This works with LM Studio's
extra, with whichever runner fills that role later, and with none: the owner is removing the LM Studio runner before
0.2.0 (#412, #413), and these tests should need no rewrite when it goes. The LM Studio-specific test becomes one that
checks the real extras against core's runner table: each runner the table puts in an extra has its extra, and `all`
names each one. With no such runner, it checks that `all` names nothing. This follows pin-tests-any-state D1 (#229):
a test builds or reads the state it needs and doesn't assume the repository's.

The releases scenarios this change re-adds unchanged (D4) still name `troupe-runner-lm-studio`, as the main spec does
today. Rewording them is #413's job, along with the rest of the spec text that names the runner.

`test_all_pinning_another_version_names_both_references[unpinned]` failed only because D3's rule fired on the
unpinned copy with the SDK released. Under D3 it passes as it is.

Each test is checked in three states of the real files: `main`, #263's branch, and that branch with
`pin_bundle.py` applied (the pinning pull request's state). The real files are copied aside and restored, never
stashed.

### D3. Remove the pinned-dependency rule (owner, 2026-11-13, option A on #411)

runner-sdk D12 added "when the bundle pins a component, every released workspace member it depends on is pinned too".
"Released" means the manifest's version is above 0.0.0. A release pull request raises the manifest, but the tag it
needs is created only when it merges, and only then does the pinning pull request pin it. So the rule fails on every
release pull request that first releases such a member, and on `main` between that merge and the pin. D12 was
written before #262. Since #262, a bundle that names any member bare excludes its own commits and doesn't release,
and the check enforces that both ways (releases spec, "The bundle doesn't release while it names a member bare"). A
`troupe-run` tag therefore can't name the SDK bare, which is the harm D12's rule guarded against. With the exclusion
gone, nothing is bare, so the rule can't fire.

So the rule goes: the installation requirement, `_unpinned_dependencies` in `scripts/bundle.py` with its module
docstring sentence, and its tests (`test_a_pinned_core_with_the_released_sdk_bare_names_both_and_the_bundle`, the
adapter-pinned-troupe-bare test after it, and the extras case in `test_release_config.py`, if there is one). A new
test runs the bundle check on a copy in the first-release state (the SDK at 0.1.0 in the manifest, the bundle
pinning core and naming the SDK bare, the exclusion present) and expects no problems. That's the releases delta's
new scenario. A second test shows the invariant still holds without the rule: the same first-release copy with the
exclusion removed, as a bundle that could release, fails the check, naming the SDK, `release-please-config.json` and
the exclusion to add (owner, 2026-11-13).

*Alternatives:*

- **B: keep the rule, applied only while the bundle's entry has no `exclude-paths`.** It keeps the requirement and its
  message, but it can never fire, because with no exclusion nothing is bare. Not chosen.
- **C: count a member released only once its tag exists** (`git ls-remote`). This puts the network and git state into
  `check.py`, which is standard library only and offline. Rejected.

### D4. The releases extras requirement is re-added under a new name

"The bundle's extras are pinned like its dependencies" lists the pinned-dependency rule and has the scenario "An
extra's runner pins the released SDK bare". OpenSpec refuses a MODIFIED block that drops a scenario, and REMOVED plus
ADDED under one name. So the requirement is removed and re-added as "The bundle's extras follow its dependencies'
rules", with the same text minus that rule, its other three scenarios unchanged, and a new scenario for the
first-release state. Archive puts it at the end of the releases spec. The comment in `test_release_config.py` that
quotes the old name is updated.

## Risks / Trade-offs

- [A later member with no exclusion could be named bare] → It can't be, because `release_config.py` fails a bare member
  without the exclusion, naming it. That's tested (`test_a_member_bare_in_an_extra_counts_as_bare` and the
  dependency cases).
- [The three-state run misses a fourth state] → The states are the only ones `main` passes through in one release
  cycle: before the release, the release pull request, and after the pin. The memory of #271's latent break is
  exactly this check.
- [release-please doesn't rebuild #263 after the merge] → It runs on every push to `main`. If #263 still fails, the
  job log shows which test, and it gets a follow-up.

## Migration Plan

Merge to `main`. release-please rebuilds #263 on that push, and its CI should pass. Rollback is a revert, which
brings back the deadlock.
