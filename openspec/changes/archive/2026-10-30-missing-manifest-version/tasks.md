# Tasks

## 1. Check the command the message names

- [x] 1.1 In the scratchpad, make a bare repository with the tags `troupe-v0.9.0`, `troupe-v0.10.0`, `troupe-runner-scripted-v0.2.0` and `protocol-v0.1.0`, and a clone of it with no tags fetched (`git clone --no-tags`) whose remote is `origin`. In the clone, run `git ls-remote --tags --sort=-v:refname origin 'troupe-v*'` (design D2). Verify the first line is `troupe-v0.10.0`, that `troupe-runner-scripted-v0.2.0` isn't listed, and that `'protocol-v*'` lists only `protocol-v0.1.0`. If any of these fails, stop and revise design D2 before going on. Record the git version it ran on in the PR description

## 2. The messages stop guessing

- [x] 2.1 In `scripts/tests/workspace/test_release_config.py`, change the expected messages of `test_a_member_missing_from_the_manifest_is_named_with_the_manifest_file`, `test_the_protocol_missing_from_the_manifest_is_named` and the manifest line of `test_a_new_package_without_release_config_is_named` to design D3's wording (components `troupe-runner-scripted`, `protocol` and `troupe-new`). Verify they fail on the current code, under both `as-is` and `released`, with the old `0.0.0` message as the difference: `uv run pytest scripts/tests/workspace/test_release_config.py`
- [x] 2.2 Add `_missing_version(path, component)` to `scripts/release_config.py` (design D3) and use it in the member loop of `problems` and in `_protocol_problems`, passing the member's project name and `PROTOCOL`. Verify the three tests pass under both ids, the rest of the file still passes, and `git grep -n '0\.0\.0' scripts/release_config.py` finds only the `"0.0.0"` inside the helper's "if it has none" clause
- [x] 2.3 Rename `test_the_protocol_missing_from_the_manifest_is_named` to say what it now checks (for example, `test_the_protocol_missing_from_the_manifest_is_named_with_its_tags`), and likewise the member test if its name no longer covers the tags. Verify each test's name matches its assertion, and the file passes
- [x] 2.4 Run `uv run scripts/check.py`, and verify all gates pass

## Workflow follow-up

- Open the PR with `Closes #197`; CI must pass on Linux, macOS and Windows.
- Act on Claude's review of the last push.
- Archive the change on the branch (`/opsx:archive`), syncing the `releases` delta into the main spec, before merging.
- After the merge, comment on #197 with the PR and the archived change, and check its card on the roadmap board says Done.
