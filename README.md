# troupe

**Your agents need a director.**

troupe runs your development process with agents and people in named roles. Work branches and loops, decisions
go to whoever owns them, and every decision records who made it.

**Status: pre-alpha.** There's nothing to install yet. What exists so far is the repository's foundation: the
workspace, the quality gates, and the first pieces of the command line and the platform seam. See
[troupe.run](https://troupe.run) for the principles, and the [roadmap](https://github.com/orgs/troupe-run/projects/1)
for the open decisions and what's next.

## Development

You need [uv](https://docs.astral.sh/uv/). It installs the right Python (3.12 or later) for you. troupe is
developed and tested on Linux, macOS and Windows.

```console
uv sync
uv run scripts/check.py
```

`scripts/check.py` runs every gate in order, and stops at the first failure: ruff (lint and format), `mypy
--strict`, the import contracts, and the tests. CI runs the same script on all three platforms, and every job
must pass.

| Where | What |
|---|---|
| `packages/troupe/` | The `troupe` distribution: the core, the command line and the platform seam |
| `plugins/` | Out-of-process plugins ([why they're separate](plugins/README.md)) |
| `protocol/` | Language-neutral contracts, as JSON Schema ([more](protocol/README.md)) |
| `openspec/` | Specs and changes ([OpenSpec](https://github.com/Fission-AI/OpenSpec)) |
| `docs/` | Reference for [the command line](docs/cli/README.md) and [the platform seam](docs/platform.md) |

How work flows, from issue to OpenSpec change to pull request, is in the
[contributing guide](https://github.com/troupe-run/.github/blob/main/CONTRIBUTING.md). Contributions are signed
off under the Developer Certificate of Origin (`git commit -s`).

## Licence

[Apache-2.0](LICENSE). The troupe name, logo and characters are trademarks of HPS.GD PTY LTD, and aren't covered
by the licence.
