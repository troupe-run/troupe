# Design

## Context

See proposal.md for why. The LM Studio runner (`lmstudio-runner`, #291) is the only runner on `main` that comes as an
extra of `troupe-run`, so it is also what most of the "a runner in an extra" scenarios and tests use as their
example. It brought three things into core with it: an entry in the runner table (`troupe.core.interim.RUNNERS`), a
built-in runtime (`troupe.core.defaults.RUNTIMES["lm-studio"]`) and an audition (`troupe.core.audition`), plus one
fit rule only it needs (`RuntimeFit.scheme="http"`, since its library has no TLS). #420 (the anthropic runner), which was
open and adds the next runner in an extra; #414 is planned. Either may merge before or after this change.

## Goals / Non-Goals

**Goals:**

- Nothing in the repository installs, imports or documents `lmstudio` or the `lm-studio` runner after this change.
  What still names it is the archive, this change, and tests that check `lm-studio` is now refused.
- Every rule that was illustrated with LM Studio (extras, `all`, pins in extras, the install check's refusal, the
  docs check, `runner.not-installed`) keeps a scenario and a test that fails when it breaks.
- The change works whether #420 merges first or second. (It merged first; this change is rebased on it.)

**Non-Goals:**

- Documenting how to run LM Studio through the anthropic runner: #415 does that.
- Changing any rule about extras, pins or fits beyond the one fit rule only LM Studio used.

## Decisions

### D1. A fixture runner, `example`, stands for a runner in an extra

Scenarios and tests that need a runner in an extra name `example`, whose plugin is `troupe-runner-example` in
`troupe-run`'s `example` extra, as #411's design D2 already does for the workspace tests (`scripts/tests/bundle_state.py`).
Core's tests register it for the test only (monkeypatching `interim.RUNNERS`, and the audition table where an audition
is needed), with a package that isn't installed where the test needs that.

*Alternatives:* name #420's `anthropic` runner. That ties this change's specs and tests to #420 merging first, and
they'd need rewriting again when the next runner in an extra replaces it. Leaving the scenarios with no example (only
"No runner has an extra yet") drops the tests that prove the rules for a runner that has one.

### D2. The plain-`http` fit rule goes with the runner

`RuntimeFit.scheme`, the `endpoint-scheme` reason and its message existed only because LM Studio's library has no TLS
(lmstudio-runner design D3). No other runner, including #420's, sets it. Keeping it would leave a rule no runner uses,
in the spec and in the code, tested only through a made-up runner. A runner that needs it later adds it back with its
own tests. Checked against #420 and #414's branches on 2026-11-14: neither sets `scheme`; they only list
`endpoint-scheme` beside their own new reasons (`endpoint-version`, `endpoint-unwanted`), and whoever merges second
drops it from that list. Refusing a credential sent over plain `http` to another machine is a different check,
`runtime.insecure-endpoint` at perform, and it stays. The `built_in` rule stays: `ollama`, `openai` and #420's `anthropic` each set it, and its scenario is
written for any runner's built-in of the same shape, tested with a stand-in built-in.

### D3. The built-in requirement is removed and re-added under a new name

OpenSpec refuses a MODIFIED block that drops a scenario, and the scenario "LM Studio's built-in is its server root"
can't be kept under that name. "troupe has built-in runtimes" is removed and re-added as "troupe defines its built-in
runtimes in one place", with the same text less `lm-studio`. The other requirements that named LM Studio keep their
scenarios by name with new content: "The LM Studio runner" (cli) and "An LM Studio actor on an https endpoint"
(runtimes) now say troupe doesn't know the runner.

### D4. `all` keeps only the anthropic runner

`troupe-run`'s extras become `all` and `anthropic` (#420), and `all` names only `troupe-runner-anthropic`. Had this
merged first, `all` would have been empty, which the installation spec already allows ("No runner has an extra yet").
The install docs that worked with the real extras (#411 D2) need no rewrite. Release-please's config and manifest lose the package. The plugin was
never released (manifest 0.0.0), so no tag or changelog needs removing.

### D5. The spec is retired, not deleted by hand

The `lm-studio-runner` delta removes all 38 requirements, and `.openspec.yaml` sets `retire_capabilities: true`, so
archive deletes `openspec/specs/lm-studio-runner/`. infrastructure's `oob/troupe-spec-purposes.json` loses that
spec's entry in a pull request merged right after this one, with its own issue and change.

## Risks / Trade-offs

- [#420 or #414 merges first and touches the same lines: runtimes spec, `interim.py`, `defaults.py`, `runtimes.py`,
  `troupe-run`'s extras, `docs/stagecraft/runtimes.md`] → whichever merges second rebases. #420 merged first, so
  this change is rebased on it: `all` keeps `troupe-runner-anthropic`, the ADDED built-ins requirement carries the
  `anthropic` built-in and its scenario, and the MODIFIED cli, quality-check and runtimes blocks carry #420's
  scenarios. RuntimeFit keeps #420's `version` and loses `scheme`.
- [A scenario names a runner that doesn't ship] → the scenarios say what each rule does to a runner in an extra; the
  fixture name is the one the workspace tests already use, and D1 says so.
- [Dropping `uv.lock` entries changes the lock] → `uv lock` regenerates it; the check's lock gate confirms it.
