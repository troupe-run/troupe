# Tasks

## 1. Workspace and gates

- [x] 1.1 Create the workspace root `pyproject.toml` (members `packages/*`, dev dependency group, ruff/mypy/pytest/import-linter config per design D8) and `packages/troupe/` with src layout and the `troupe` console script; verify `uv sync` succeeds and `uv run python -c "import troupe"` exits 0
- [x] 1.2 Add `scripts/check.py` running ruff, `ruff format --check`, `mypy --strict`, `lint-imports` and pytest in that order, stopping at the first failure; verify it passes on the empty package and fails when a deliberate lint error is added (then removed)
- [ ] 1.3 Add `plugins/README.md` (out-of-process rule, JSON-RPC over stdio, imports only `protocol/`) and `protocol/README.md` (language-neutral contracts, generation plan per #7); verify both render on GitHub

## 2. Errors and the protocol schema

- [x] 2.1 Add `protocol/schemas/error.schema.json` (code, problem, fix, optional path and details; design D3) and the mirroring error type in `troupe.core`; verify with a test that serialises each error variant and validates it against the schema
- [x] 2.2 Add the exit-code table in `troupe.core` (0, 1, 2; design D4) and `docs/cli/exit-codes.md`; verify with a test that the document lists exactly the enum's codes

## 3. CLI (spec: cli)

- [ ] 3.1 Implement the argparse root with a shared global-options parent (design D2) and `--version`; verify the "Version outside any theatre" scenario with a test that runs the installed console script in an empty temp directory
- [ ] 3.2 Implement global flags anywhere; verify both "Global flags are accepted anywhere" scenarios using a test-only subcommand
- [ ] 3.3 Implement the `--` convention for dash-leading values; verify the "Dash-leading value without separator" scenario
- [ ] 3.4 Implement error rendering (stderr only, empty stdout, non-zero exit) and an unexpected-error fallback (code 1, still structured); verify the "An error names the problem and the fix" and "Error data matches the protocol schema" scenarios
- [ ] 3.5 Implement unknown subcommand and flag handling with difflib suggestions; verify the "Unknown subcommand with a near match" and "Unknown flag" scenarios and the "Every returned code is documented" scenario across the CLI test suite
- [ ] 3.6 Document the CLI's global flags and error format in `docs/cli/README.md`; verify every documented command runs as written

## 4. Platform seam (spec: platform)

- [ ] 4.1 Implement atomic replacement on POSIX and Windows (design D5); verify "Permissions are kept" and "Write fails part-way" (inject a failure before replace), plus a hypothesis property test that arbitrary byte contents (BOM, CRLF, no final newline, empty) round-trip exactly
- [ ] 4.2 Verify "Reader never sees a partial write" with a multi-process test that replaces a file repeatedly while a reader checks every read is one complete version
- [ ] 4.3 Implement lock-file locks (`flock` on POSIX, `msvcrt.locking` on Windows) with announce callback, timeout and nested-acquisition refusal (design D6), with defaults in `troupe.core.defaults`; verify "Lock held by another process" (second process, short timeouts), "Timeout comes from a named setting" and "Nested acquisition"
- [ ] 4.4 Implement friendly path display with the platform separator (design D5a); verify the three path scenarios plus a hypothesis test that the output is never relative and starts with `~` plus the separator exactly when the path is under home
- [ ] 4.5 Implement the bounded, announced retry when the replace target is held open (design D5); verify "Target held open by another process" on Windows by holding the file open from a second process, and confirm the test isn't skipped on any platform where the condition can be produced
- [ ] 4.6 Verify "The same tests pass on every platform": run the platform suite on a Windows machine locally (owner's session) as well as in CI, and check `pytest -rs` reports no skips for a missing platform implementation on any of the three
- [ ] 4.7 Document the platform seam (what lives there, how each platform differs inside it, the NFS limitation) in `docs/platform.md`

## 5. Import contracts

- [ ] 5.1 Add import-linter contracts for the `cli` → `core` → `platform` layers and for OS-specific modules being imported only in `platform` (design D7); verify `lint-imports` passes, then introduce one deliberate violation of each contract, confirm each fails, record the output for the PR, and remove the violations

## 6. CI

- [ ] 6.1 Add `.github/workflows/ci.yml`: matrix {ubuntu, macos, windows} × {3.12, 3.13} running `scripts/check.py`, all jobs required; verify by pushing the branch and confirming all six jobs pass, and record per-job durations

## 7. Contributing and DCO

- [ ] 7.1 Don't add a repo-level `CONTRIBUTING.md`: the org default in `troupe-run/.github` covers the DCO and the workflow, and a repo file would replace it entirely. Put the repo-specific part (how to run `scripts/check.py`) in `README.md` under "Development", which the org default points to; verify the commands run as written and that GitHub's contributing link on this repo shows the org default
- [ ] 7.2 Install the DCO GitHub App on the repo (owner, from the GitHub UI) **before the bootstrap PR is opened**. `dco.yml` (`require: members: false`, design D10) is already on the default branch of `troupe-run/.github`, the org-wide fallback the app reads when a repo has none; the app is installed on both repos. Verify both paths: the bootstrap PR's commits (signed by an org member, no sign-off) pass, and a throwaway PR with an unsigned commit and no sign-off fails until it's amended with `git commit -s`. If the member path fails because the owner's org membership is private, record it and decide with the owner: make the membership public, or sign off anyway. Making the check required is a ruleset in #19
- [ ] 7.3 Update `README.md` with what troupe is (site wording), status (pre-alpha), licence, and links to the org contributing guide and the roadmap project

## Workflow follow-up

- Open the PR with "Closes #18" and the OpenSpec change name; after merge, archive the change (answer the archive prompt up front), then comment on #18 with the PR and change, and close it.
- Comment on #17 with the first CI run's per-job durations.
