# Tasks

## 1. Declare and enforce the bound

- [x] 1.1 Set `requires-python = ">=3.12,<3.14"` in all nine `pyproject.toml` files (root, the seven under
  `packages/`, `plugins/runner-scripted/`). Re-lock with `uv lock`. Verify with
  `grep -rn requires-python --include=pyproject.toml .` (nine identical lines), `uv sync --locked` succeeding, and
  `uv.lock`'s `requires-python` reading `>=3.12, <3.14`
- [x] 1.2 Add `.python-version` holding `3.12`. Verify `uv run python -V` reports 3.12 on this machine (3.13, 3.14
  and 3.15 are installed)
- [x] 1.3 Verify the refusal (spec: an unsupported interpreter is refused): `uv run --python 3.14 scripts/check.py`
  and `UV_PYTHON=3.15 uv run python -V` both fail, naming `>=3.12, <3.14`. Record the output in the PR
- [x] 1.4 After the PR's CI runs, confirm from the logs that the 3.13 jobs ran on 3.13 and the 3.12 jobs on 3.12
  (design D4: `UV_PYTHON` overrides `.python-version`)

## 2. One decision, checked in one place

- [x] 2.1 Write `scripts/tests/test_python_versions.py` first, in `test_release_config.py`'s style (break one
  property in a copy of the real files, assert the exact message). Cover: a member that differs (names its file and
  the root's bound); a root bound with no upper limit, and one not of the form `>=3.X,<3.Y` (`~=3.12`, `<3.12,>=3.14`
  inverted); a CI matrix missing a version, with an extra version, with no `python:` line, and with two; an entry
  that isn't a quoted `3.N`; `.python-version` above the lowest; ruff `target-version` and mypy `python_version` not
  the lowest; and the real repository having no problems. Verify they fail before 2.2 for the right reason (missing
  module)
- [x] 2.2 Implement `scripts/python_versions.py` (standard library only): `supported(root)` parsing the root's bound
  (design D2), and `problems(root)` per design D1/D3, reusing `release_config.members` for the member list. Verify
  2.1's tests pass and `uv run scripts/check.py` passes
- [x] 2.3 Add a hypothesis property test for the bound parser: for any X < Y, `>=3.X,<3.Y` (with arbitrary spaces)
  gives exactly X..Y-1, and any generated string not of that form raises an error naming `pyproject.toml`. Verify it
  passes under `uv run pytest scripts/tests`

## 3. Switch versions in one command

- [x] 3.1 Write `scripts/tests/test_on.py` first. Cover: a malformed version (`3.x`, `3`, `3.13.1`, empty) is refused
  with the form shown and nothing run; an unsupported version (`3.15`) is refused listing 3.12, 3.13 and the bound,
  and uv isn't invoked; a supported version builds the uv command with `--python 3.13` and
  `UV_PROJECT_ENVIRONMENT=<repo>/.venvs/3.13`, runs from the repository root, and forwards arguments unchanged
  (including ones starting with `-`); the exit code is passed through. Verify they fail before 3.2
- [x] 3.2 Implement `scripts/on.py` (design D5) with a PEP 723 header and no dependencies. Add `.venvs/` to
  `.gitignore`. Verify 3.1's tests pass, `git status` stays clean after a run, and `uv run ruff check .` doesn't lint
  inside `.venvs/`
- [x] 3.3 End-to-end on this machine (spec: switching back and forth): run `uv run scripts/on.py 3.13 python -V`, then
  `uv run python -V`, then `on.py 3.13` again. Verify the versions reported are 3.13, 3.12 and 3.13, `.venv` and
  `.venvs/3.13` both exist, and the second 3.13 run doesn't recreate the environment (no "Creating virtual
  environment" line). Then run `uv run scripts/on.py 3.13 scripts/check.py` to a pass

## 4. Docs

- [x] 4.1 Update the README's Development section: the supported versions (3.12 and 3.13) are exactly what CI tests
  and uv refuses others; plain `uv run` uses 3.12; `uv run scripts/on.py 3.13 <command>` runs on another supported
  version in `.venvs/3.13`, which is safe to delete; and adding a version means changing the bound and the CI matrix
  together, which the check enforces. Verify each command in the section runs as written

## 5. Integration

- [x] 5.1 Run `uv run scripts/check.py` to a pass on a clean `uv sync --locked`, and `openspec validate
  python-version-bounds --strict` to a pass

## Workflow follow-up

- Open the PR with `Closes #105` (Part 1's sub-issue of #104). #104 and its card stay open and In Progress.
- Archive on the branch before merging. After merging, check that #105 is closed and its card says Done, and comment
  on #105 with the PR and the archived change. Then open Part 2's sub-issue of #104 (3.14 and 3.15 in CI, bound
  `<3.16`) and propose it as its own change.
