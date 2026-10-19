# troupe

**Your agents need a director.**

troupe runs your development process with agents and people in named roles. Work branches and loops, decisions
go to whoever owns them, and every decision records who made it.

**Status: pre-alpha.** There's nothing to install yet. What exists so far is the repository's foundation: the
workspace, the quality gates, and the first pieces of the command line and the platform seam. See
[troupe.run](https://troupe.run) for the principles, and the [roadmap](https://github.com/orgs/troupe-run/projects/1)
for the open decisions and what's next.

## Development

You need [uv](https://docs.astral.sh/uv/). It installs the right Python for you. troupe is developed and tested
on Linux, macOS and Windows.

```console
uv sync
uv run scripts/check.py
```

troupe supports Python 3.12 to 3.15, exactly the versions CI tests. Every `pyproject.toml` says so
(`requires-python = ">=3.12,<3.16"`), and uv refuses any other version, naming the bound. Plain `uv run` uses
3.12, the lowest. To run on another supported version, name it:

```console
uv run scripts/on.py 3.15 scripts/check.py
```

Each version gets its own environment in `.venvs/`, so switching back and forth rebuilds nothing. Delete
`.venvs/` whenever you like. To support a new Python version, widen the bound and add the version to CI's matrix
in the same change. `scripts/check.py` fails if either moves without the other.

`scripts/check.py` runs every gate in order, and stops at the first failure: ruff (lint and format), `mypy
--strict`, the import contracts, and the tests. CI runs the same script on all three platforms and every
supported Python version. A pull request runs what its changed paths need, as a commit does: nothing for a change
only to `openspec/`, the scoped check for scoped paths, and the full check otherwise. `main` runs the full check
after every merge. The one required check, `check`, passes when every platform's run passed, or when none was
needed.

The check runs the tests in parallel with pytest-xdist, one worker for each CPU it may use. Set
`PYTEST_XDIST_AUTO_NUM_WORKERS` to change the count. Running pytest yourself (`uv run pytest ...`) stays in one
process, which is easier for narrowing to one test or stepping through it in a debugger.

Turn on the repository's git hooks once per clone (Claude Code sessions do this for you):

```console
git config core.hooksPath .githooks
```

They refuse commits on `main`, commits on a branch with no matching OpenSpec change, messages that aren't
Conventional Commits, and commits whose checks fail.

A commit runs only what its staged paths need, as `scripts/check-paths.toml` declares. A commit that changes only
`openspec/` skips the check. One that changes only `docs/` (or the scripted runner's README) runs every gate, but
only the tests that check the docs against the code. One that changes only one package outside core, or only
`scripts/`, runs every gate, but only the test suites that reach what it changed. Anything else runs the full check,
including core, any package's `pyproject.toml`, and `check.py` and the guard files. To run a scope by hand:

```console
uv run scripts/check.py --scope docs
uv run scripts/check.py --scope store_text
```

Every test run also checks the declaration. A test that reads a scope's path without that scope's tag, or that reads
anything under `openspec/`, fails and is named. A full run also fails when a scope's `tests` aren't exactly the suites
that reach its package; `uv run scripts/check_paths_reach.py` prints the lists to declare. The rules are maintained in `troupe-run/infrastructure`, and
[development-workflow.md](https://github.com/troupe-run/infrastructure/blob/main/docs/development-workflow.md) lists every rule and how an override works.

| Where | What |
|---|---|
| `packages/troupe/` | The `troupe` distribution: the core, the command line and the platform seam |
| `plugins/` | Out-of-process plugins ([why they're separate](plugins/README.md)) |
| `protocol/` | Language-neutral contracts, as JSON Schema ([more](protocol/README.md)) |
| `openspec/` | Specs and changes ([OpenSpec](https://github.com/Fission-AI/OpenSpec)) |
| `docs/` | Reference for [the command line](docs/cli/README.md), [the platform seam](docs/platform.md), [the event store](docs/event-store.md), [releasing](docs/releasing.md) and [hunting flaky tests](docs/flake-hunt.md) |

How work flows, from issue to OpenSpec change to pull request, is in the
[contributing guide](https://github.com/troupe-run/.github/blob/main/CONTRIBUTING.md). Contributions are signed
off under the Developer Certificate of Origin (`git commit -s`).

## Licence

[Apache-2.0](LICENSE). The troupe name, logo and characters are trademarks of HPS.GD PTY LTD, and aren't covered
by the licence.
