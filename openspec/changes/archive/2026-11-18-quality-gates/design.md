# Design: quality-gates

## Context

troupe-run/infrastructure's `quality-gates` change (infrastructure#328) built the gates and their measures, and
delivers `scripts/quality_gates.py` here. Its design (D1–D9, "Owner's decisions" of 2026-11-18) is the source for
what each gate does; this design covers troupe's side only. troupe runs `scripts/check.py` on 12 CI legs (Linux,
macOS, Windows × Python 3.12–3.15) and before every commit.

## Goals / Non-Goals

**Goals:** troupe's thresholds in `quality-gates.toml`; the complexity gate on every check; coverage and the audit on
the Linux 3.15 leg only; runner code measured; the weekly report.

**Non-goals:** raising coverage (#325's mutation testing raises issues for weak spots); refactoring today's complex
functions; changing what the gates measure (that's infrastructure's module).

## Decisions

### D1. The runner policy passes coverage.py's variable, and only it

`defaults.RUNNER_ENVIRONMENT` becomes `EnvironmentPolicy(names=frozenset({"COVERAGE_PROCESS_CONFIG"}))` (owner,
2026-11-18, option (a) of two). coverage.py's subprocess measurement puts its settings in that variable and starts
measuring any Python process that has it. troupe's runner policy passed nothing, so no runner process was measured.
Patching the policy from pytest recovered nothing (runner-scripted 51.8% and runner-claude-code 61.1% either way),
because the tests start runners from the CLI's own process.

The variable carries coverage settings (paths, options), never a credential, and is set only when someone runs troupe
under coverage. A name, not a prefix: `COVERAGE_` would pass `COVERAGE_FILE` and anything else that happens to start
that way. The spec's new scenario holds it to exactly one.

*Rejected:* (b) recording the runners' baselines as measured, which would make the floor meaningless for runner code
and leave a third of the codebase effectively unmeasured.

### D2. The config

```toml
version = 1

[coverage]
floor = 80.0
tolerance = 0.6    # from two CI runs (D8)

[coverage.packages.troupe]
paths = ["packages/troupe"]
baseline = 91.9    # each from the coverage leg (D8)
# … one per workspace member under packages/ and plugins/, and scripts

[complexity]
block_above = 25
languages = ["python"]
exclude = ["**/tests/**", "scripts/guard.py", "scripts/guard_pytest.py", "scripts/quality_gates.py",
           "scripts/mutation_*.py", "packages/troupe/src/troupe/core/config/models.py"]

[audit]
lock_files = ["uv.lock"]
block = ["high", "critical"]
```

Every package covers its whole directory (`packages/troupe`, `plugins/runner-claude-code`), so a plugin's `tools/`
count with it; tests are left out by coverage.py's `omit`, not by the package's paths.
`troupe-run` is a metapackage with no code; it's listed so a file added there has a home, and it reports "nothing to
measure". coverage.py measures `packages`, `plugins` and `scripts`, omitting tests and the delivered files, in
`[tool.coverage.run]` in `pyproject.toml`, with `patch = ["subprocess"]`.

### D3. Where each gate runs

Complexity runs on every leg, so every leg needs the base: `actions/checkout` with `fetch-depth: 0`, and the step
passes `--base`: a pull request's merge commit's first parent, a merge group's `base_sha`, or a push's `before`.
The Windows step does the same in PowerShell. Coverage and the audit run on the `ubuntu-latest`, `3.15` leg only,
marked `gates: true` in the matrix's `include`, which sets `QUALITY_GATES_LEG`. `check.py` follows infrastructure's:
the variable outside GitHub Actions, or set to anything but `true`, stops the check.

The coverage leg runs the tests under coverage, which costs that leg some time; the leg limit (20 minutes) has room,
and the cost is measured on this change's pull request.

### D4. The weekly report

`.github/workflows/dependency-report.yml`, as infrastructure's: Mondays, `quality_gates.py report`, and a `board` job
with the `board` environment infrastructure#328 declares here (the owner sets its key after that apply).

### D5. Sequencing

The runner policy (D1) can land on its own: it changes no gate. The rest needs `scripts/quality_gates.py`, which
arrives by delivery after infrastructure#328 merges and its plan is applied; `check.py` can't run the gate before
then. Baselines are measured on this pull request's coverage leg, with D1 in place.

### D6. Runners end through an SDK exit that lets coverage save (owner, 2026-11-18)

D1 passed coverage.py's variable to runners, but this pull request's coverage leg still measured runner-scripted at
51.8% and runner-claude-code at 61.1%. Every runner ends with `os._exit` on purpose (a reader thread may still be
blocked on standard input or a pipe), and `os._exit` skips the `atexit` hook where coverage.py saves, so a runner
process's measurement was always lost. An experiment that let coverage save before `os._exit` took runner-scripted's
own tests from 52.4% to 78.4%.

The owner chose (a) of two: the plugin SDK gets `troupe_plugin_sdk.process.exit_now(code)`, used by all six runners in
place of `os._exit`. When coverage.py is already measuring the process (found through `sys.modules`, never imported)
it stops and saves it, then calls `os._exit`; without coverage it is exactly `os._exit`. *Rejected:* (b) record the
runners' baselines as measured and revisit later.

### D7. Omit patterns are globs

coverage.py reads a relative `omit` pattern against each process's own working directory, and the tests start many
processes from temporary directories, so `scripts/guard.py` was measured in those and the delivered files counted in
`scripts` (44.2% on CI against 88.3% measured locally without them). The patterns are `*/scripts/guard.py` and the
like, which match from any directory.

CI then measured `scripts` at 71.9%. The coverage leg's report (now kept as an artifact) showed every file troupe owns
measuring the same on CI as locally; the difference was five `scripts/mutation_*.py` files that infrastructure#325
delivers (626 statements, untested here, as they're tested at their source). Leaving them out too gives 88.5% on CI,
the local figure. They're left out of coverage and complexity by pattern; `.github/guard-delivery.json` lists every
delivered file, so the delivered module could read it and leave them all out by itself, which is a change for
troupe-run/infrastructure.

### D8. Baselines and tolerance

Two runs of the coverage leg on f9f6bd6a (CI run 44240981380, attempts 1 and 2), with the runner exit (D6) and the
omit fix (D7) in place, measured every package identically except runner-openai: 91.06% and 91.59%, a difference of
0.53 points from timing-dependent paths in its tests. So the tolerance is 0.6, the smallest tenth that covers it
(infrastructure's quality-gates design D4), and each baseline is the lower measurement rounded down to 0.1:

| Package | Baseline | | Package | Baseline |
|---|---|---|---|---|
| troupe | 91.9 | | runner-anthropic | 86.5 |
| troupe-artifacts-local | 91.7 | | runner-claude-code | 72.7 |
| troupe-identity-local | 96.1 | | runner-mistralrs | 88.0 |
| troupe-plugin-sdk | 94.9 | | runner-ollama | 89.6 |
| troupe-stage-local | 100.0 | | runner-openai | 91.0 |
| troupe-store-text | 93.0 | | runner-scripted | 81.7 |
| troupe-vcs-files | 95.2 | | scripts | 88.4 |
| troupe-vcs-git | 93.3 | | troupe-run | (no code) |

Before D6 the runners measured 50.7% (scripted) to 91.5%; runner-claude-code, at 72.7%, is the one package under the
80% floor a new package must meet, which it would fail if it were new. #325's mutation testing reports weak spots.

