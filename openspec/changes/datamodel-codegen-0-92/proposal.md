# Proposal

## Why

Dependabot's #445 updates datamodel-code-generator from 0.87.0 to 0.92.0 (tracked by #432). Under 0.92 the generator
lays out `packages/troupe/src/troupe/core/config/models.py` differently, so
`test_config_schemas.py::test_the_models_are_what_the_schemas_generate` fails on every CI leg (#447). The update
changes a file other than dependency files, so the guard's `commit-branch-change` doesn't exempt it, and it needs an
OpenSpec change of its own (development-workflow, "Dependabot pull requests").

## What Changes

- The root `pyproject.toml`'s dev group requires `datamodel-code-generator>=0.92.0,<0.93` (was `>=0.87.0,<0.88`), and
  `uv.lock` resolves it to 0.92.0: Dependabot's own commit from #445, carried as it is (design D2).
- `models.py` is regenerated with `uv run scripts/generate_models.py`. The only difference is layout: one
  `StringConstraints(...)` call in `Runtime` is wrapped one argument per line. The old and new files parse to the
  same Python AST, so every model, type, default, constraint, alias and `extra` setting is unchanged, and no config
  is accepted or read differently (design D1).

No product behaviour changes, so no spec changes (`skip_specs: true`). The config spec's generated-models
requirement holds as it is: the test that runs `generate_models.py --check` passes under 0.92.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None.

## Impact

- `pyproject.toml` (one line), `uv.lock` (the generator's entry and the dev group's specifier), and
  `packages/troupe/src/troupe/core/config/models.py` (layout only).
- No release: the generator is a dev dependency, and the regenerated module behaves the same, so `models.py` is
  committed as `style(config)`, a type release-please releases nothing for (design D2).
- Closes #447 and #432. Dependabot's #445 is closed as up to date once this change's pull request merges (design D3).
