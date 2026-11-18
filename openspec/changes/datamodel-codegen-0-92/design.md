# Design

## Context

See proposal.md, "Why". `scripts/generate_models.py` bundles the config schemas and runs datamodel-code-generator with
fixed options (`GENERATOR_ARGS`: pydantic v2 models on `StrictModel`, annotated constraints, enums as literals, the
`builtin` formatter). `test_the_models_are_what_the_schemas_generate` runs the script's `--check`, which compares the
committed `models.py` with fresh output byte for byte, so any change in the generator's output fails it, layout
included.

## Goals / Non-Goals

**Goals:**

- Land Dependabot's update with `models.py` regenerated, showing the new output means the same as the old.

**Non-Goals:**

- Changing the generator's options, or using anything 0.88 to 0.92 adds.
- Making `--check` ignore layout. A byte comparison is what keeps `models.py` exactly what the schemas generate.

## Decisions

### D1. The regenerated models are the same models: compare their AST

Each kind of change that could alter how a config is accepted or read (a type, a default, whether a field is
required, a constraint, a validator, an alias, the `extra` setting, an enum's shape) changes the module's syntax tree.
Layout and line wrapping don't. So the old and new `models.py` are parsed with `ast.parse` and their `ast.dump`
compared. Under 0.92 they're identical. The only textual change is in `Runtime`:

```python
# 0.87
StringConstraints(
    pattern=r"^(?![\s\S]*[\x00-\x1f\x7f])[\s\S]+$", min_length=1, max_length=256
),
# 0.92
StringConstraints(
    pattern=r"^(?![\s\S]*[\x00-\x1f\x7f])[\s\S]+$",
    min_length=1,
    max_length=256,
),
```

Dependabot's lock change moves only datamodel-code-generator's entry. pydantic, which the models run on, doesn't
move, so the same tree behaves the same. Alternatives considered: reading the diff by eye alone (fine for three
lines, but it doesn't prove there's nothing subtler), or diffing each model's `model_json_schema()` (also works, but
it compares a projection of the models, not the models).

### D2. Carry Dependabot's commit, then add the regeneration as `style(config)`

The branch starts from Dependabot's commit `chore(deps-dev): Bump datamodel-code-generator from 0.87.0 to 0.92.0`
unchanged. It's the update the workflow asks for, already signed off, and its `pyproject.toml` and `uv.lock` lines are
exactly #445's. The regenerated `models.py` follows as its own commit. Its type is `style`: the change is layout
only (D1), and release-please releases nothing for `style`, so troupe isn't released for it. `models.py` isn't under
`protocol/schemas/`, so `schema-commit-type` doesn't apply. Alternatives considered: `fix(config)`, which would
release a patch whose code doesn't change, and pushing to Dependabot's branch, which its ruleset refuses to anyone
but Dependabot.

### D3. #445 is closed only after this change merges

Closing a Dependabot pull request while its issue (#432) is open closes the issue as not planned an hour later. So
this change's pull request closes #432 and #447 when it merges. Dependabot then closes #445 as up to date, or, if it
is still open, it's closed by hand with a comment linking this pull request.

## Risks / Trade-offs

- [A later 0.92.x or 0.93 changes the output again] → The same test fails on that Dependabot pull request, and the
  same AST comparison sorts layout from behaviour.

## Migration Plan

None: a dev dependency and a layout-only regeneration. To roll back, revert both commits.
