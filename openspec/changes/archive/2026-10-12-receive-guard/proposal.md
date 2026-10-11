# Proposal

Issue: #30. The other half of troupe-run/infrastructure#8 (Decision #25).

## Why

The development workflow's spec and its guard govern how the org builds software, not what troupe does. Decision #25
moved them to `troupe-run/infrastructure`, which now holds the spec and the guard's source, and delivers the guard's
files to troupe. troupe still carries its own copy of the spec, the guard's tests and the rules doc, so there are two
editable copies until this change removes troupe's.

## What Changes

- **Retire the `development-workflow` capability** here. Each of its requirements now lives in
  `troupe-run/infrastructure/openspec/specs/development-workflow`.
- **Remove the guard's tests** (`scripts/tests/test_guard_*.py`). They run in infrastructure, on Linux, macOS and
  Windows. `test_check_activation.py` stays: it tests troupe's own `scripts/check.py`. So does `conftest.py`, whose
  helpers it uses.
- **Remove `docs/development-workflow.md`.** The rules doc lives in infrastructure.
- **Point `CLAUDE.md`, `README.md` and `scripts/check.py`** at infrastructure's rules doc and spec.

Not changed: `scripts/guard.py`, `.githooks/`, `.claude/settings.json` and `.github/workflows/guard.yml`. infrastructure
owns them. Its next delivery updates them, adds `.github/guard-delivery.json`, and from then on they change only
there. This change must merge before that delivery, because the old `test_guard_docs.py` would fail against the
delivered guard's new rule.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `development-workflow`: retired. Every requirement is removed here and kept in `troupe-run/infrastructure`.

## Impact

- **troupe's check is quicker:** about 185 guard tests leave its test run. Its CI no longer tests the guard on three
  platforms; infrastructure's CI does.
- **No behaviour change for contributors:** the hooks, the Claude Code hooks and the `guard` check are untouched.
