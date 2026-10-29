# Proposal

Issue: #195.

## Why

When troupe can't find a runner plugin's published schemas, `schemas.plugin-missing`
(`troupe.core.schemas.plugin_schemas_directory`) tells the person to "Install the plugin (uv sync, in a checkout of
troupe)". Since #144 (PR #192) the documented way to get troupe is `uv tool install` of the `troupe-run` bundle, and
that person has no checkout to run `uv sync` in. The fix only fits a contributor, so the people most likely to meet a
missing runner (a broken or partial tool install) are told to do something they can't.

## What Changes

- **The `schemas.plugin-missing` fix for an uninstalled plugin names both ways troupe is run:** reinstall troupe with
  the install command on the install page (`https://troupe.run/docs/opening-night/install/`), since `troupe-run`
  brings every runner troupe knows; or, when running troupe from a checkout of this repository, `uv sync` there. One
  fix that is right for both, rather than troupe guessing which kind of install it is in (design D1).
- **The fix links to the install page rather than repeating the command**, so the command stays in the one form the
  installation spec requires (design D2). A test fails if the linked page moves out of `docs/`.
- **`packages/troupe/tests/test_schemas.py` checks the fix's wording**, not only the error code and details.
- No other refusal tells an installed troupe to `uv sync`: `grep -rn "uv sync" packages/*/src plugins/*/src` finds
  only this one (checked again 2026-10-30). The second `schemas.plugin-missing` refusal, for an installed plugin that
  doesn't publish a named schema, is aimed at the plugin's author and points at `contributing/runners.md`; it stays.
- The error's code and `details` (`{"package": ...}`) don't change, so `error.schema.json` doesn't either.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `protocol`: "A plugin's published schemas are installed with it" gains a scenario for a runner that isn't
  installed: the refusal names the package, and its fix names the install page for an installed troupe and
  `uv sync` for a checkout.

## Impact

- `packages/troupe/src/troupe/core/schemas.py` (`plugin_schemas_directory`'s fix text, and a named constant for the
  install page's address).
- `packages/troupe/tests/test_schemas.py`.
- `openspec/specs/protocol/spec.md`, through the delta.
- No change to the CLI, the error schema, the docs pages, or the install check.
- Out of scope: once plugins are named in config (#38), a missing plugin may be one `troupe-run` doesn't bring, and
  "reinstall troupe" stops being the whole answer. That refusal is for #38 to word.
