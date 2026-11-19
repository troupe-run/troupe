# Proposal: size-gate

## Why

troupe-run/troupe#478. A review reads every changed file whole, and one Read holds about 25,000 tokens, so a file far
above that is never reviewed in one go (troupe-run/infrastructure#271). infrastructure#349 (change `gate-files`)
delivered a `quality_gates.py` with a size gate, `[size]` optional until each repository declares it, and taught every
gate to leave out the files `.github/guard-delivery.json` lists. troupe now declares its limits, which the owner set on
2026-11-19, and stops listing delivered files by hand.

## What Changes

- `quality-gates.toml` declares `[size]`: warn above 32 KiB (32,768 bytes), block above 48 KiB (49,152), with fixtures,
  archived OpenSpec changes and `uv.lock` left out. `[size.allow]` gives each file over 48 KiB today a ceiling of its
  size rounded up to a whole KiB plus 16 KiB, and names its split issue (#471 to #477). The delivered gate fails on an
  entry once its file fits, so the list only shrinks.
- `scripts/check.py` runs `quality_gates.py size` on every run, local and on every CI leg, beside complexity, with the
  same `--base`.
- `[complexity] exclude` and `[tool.coverage.run] omit` drop their hand-written delivered-file patterns
  (`scripts/guard.py`, `scripts/guard_pytest.py`, `scripts/quality_gates.py`, `scripts/mutation_*.py`): the gates read
  the delivery list instead, which also covers the newly delivered `scripts/quality_audit.py`.
- `contributing/quality-gates.md` describes the size gate and says delivered files are left out by the delivery list.

## Capabilities

### New Capabilities

None. The size gate's behaviour is infrastructure's `quality-gates` spec.

### Modified Capabilities

- `quality-check`: the check runs the size gate everywhere, with troupe's limits in `quality-gates.toml`.

## Impact

- `quality-gates.toml`, `pyproject.toml` (`[tool.coverage.run] omit`), `scripts/check.py` and
  `scripts/tests/test_check_gates.py`, `scripts/tests/test_check_scope.py`, `contributing/quality-gates.md`.
- Every commit's check and every CI leg now fails on a file the work makes larger than its limit, and notes each changed
  file above 32 KiB.
- Coverage.py now also traces the delivered scripts on the coverage leg; the gate drops them from the measure, so the
  `scripts` package's figure is unchanged.
