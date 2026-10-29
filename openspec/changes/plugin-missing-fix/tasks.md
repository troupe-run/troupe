# Tasks

## 1. Tests first

- [ ] 1.1 In `packages/troupe/tests/test_schemas.py`, extend `test_a_plugin_that_isnt_installed_is_refused_naming_it` (or add a sibling named for what it checks, such as `test_a_missing_plugins_fix_names_the_install_page_and_uv_sync_in_a_checkout`) to assert the refusal's `fix` contains `schemas.INSTALL_PAGE`, says to reinstall troupe, and names `uv sync` only for a checkout of troupe. Verify it fails on main's wording: `uv run pytest packages/troupe/tests/test_schemas.py -k plugin` fails (no `INSTALL_PAGE`, fix is checkout-only)
- [ ] 1.2 Add `test_the_install_page_the_fix_links_to_is_in_the_docs` (design D3): `INSTALL_PAGE` starts with `https://troupe.run/docs/` and ends with `/`, and `ROOT / "docs" / "<path>.md"` exists, the assertion message naming the address. Verify it fails before 2.1 (no constant) and, after 2.1, fails when the constant is temporarily pointed at `.../opening-night/installing/`

## 2. Fix

- [ ] 2.1 In `packages/troupe/src/troupe/core/schemas.py`, add `INSTALL_PAGE = "https://troupe.run/docs/opening-night/install/"` with a docstring saying it's where the install command lives (design D2), and replace `plugin_schemas_directory`'s fix with design D1's wording built from it. Leave the code, `details` and `plugin_schema`'s refusal unchanged. Verify `uv run pytest packages/troupe/tests/test_schemas.py` passes, and `grep -rn "uv sync" packages/*/src plugins/*/src` shows only the new fix's checkout clause
- [ ] 2.2 Check the refusal as a person sees it, from a real install without the scripted runner: `uv tool install` this checkout's `packages/troupe` alone (not `troupe-run`) with `UV_TOOL_DIR` and `UV_TOOL_BIN_DIR` set to scratchpad directories, then in a new theatre in the scratchpad give an actor the `scripted` runner and set one of its options (`troupe config set actors.<name>.options.<key> ...`). Verify the command exits non-zero with `schemas.plugin-missing` and stderr shows the new fix with the install page's address. Record the output in the PR description, and remove the scratchpad tool directories afterwards

## 3. Check

- [ ] 3.1 Run `uv run scripts/check.py` and verify every gate passes

## Workflow follow-up

- Open the PR with `Closes #195`; CI must pass on Linux, macOS and Windows.
- Act on Claude's review of the last push, then archive on the branch (`/opsx:archive`), syncing the `protocol` delta, before merging.
- After the merge, comment on #195 with the PR and the archived change, and check its card on the roadmap board says Done.
