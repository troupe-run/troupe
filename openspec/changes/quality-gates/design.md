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
tolerance = 0.5

[coverage.packages.troupe]
paths = ["packages/troupe/src"]
baseline = …   # each from the coverage leg when the gate lands
# … one per workspace member under packages/ and plugins/, and scripts

[complexity]
block_above = 25
languages = ["python"]
exclude = ["**/tests/**", "scripts/guard.py", "scripts/guard_pytest.py", "scripts/quality_gates.py",
           "packages/troupe/src/troupe/core/config/models.py"]

[audit]
lock_files = ["uv.lock"]
block = ["high", "critical"]
```

A plugin's package covers the whole plugin directory (`plugins/runner-claude-code`), so its `tools/` count with it.
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
