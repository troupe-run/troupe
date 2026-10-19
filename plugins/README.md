# plugins

Out-of-process plugins: actor runners, stages, guests and notification channels. **They run over JSON-RPC, ours
included**, so a stage that can enforce declared effects can enforce them on a plugin, and a plugin can be written
in any language (decision [#37](https://github.com/troupe-run/troupe/issues/37)). Running out of process isn't a
sandbox by itself: what a plugin can touch is up to the stage it runs on, and policy (decision
[#3](https://github.com/troupe-run/troupe/issues/3)).

Rules for everything in this directory:

- **A plugin is a separate process** that troupe starts and talks to with JSON-RPC over stdio. The messages are
  defined in [`protocol/`](../protocol/). A containerised plugin is the same thing, run inside `docker run`.
- **A plugin imports only the protocol, never `troupe`.** It sees troupe exactly as a third party would, so
  first-party plugins prove the contract is complete. An import-linter contract (`plugins import nothing from
  troupe`) enforces it, and `scripts/check.py` fails when it breaks.
- **Each plugin is self-contained:** its own `pyproject.toml` (or its language's equivalent), tests and, where it
  needs one, a container image. That lets it move to its own repository later with its history
  (`git filter-repo`).

Adapters bundled with troupe (storage, version control, built-in identity sources) are not plugins. They live
under [`packages/`](../packages/) and run direct, in process, because they ship with core and sit deep in the
house. #37 gives every port a JSON-RPC transport too, so an adapter acquired by config runs as a plugin
([#38](https://github.com/troupe-run/troupe/issues/38)).

| Plugin | What it is |
|---|---|
| [`runner-scripted/`](runner-scripted/README.md) | A deterministic actor runner for tests: plays a script or replays a recording, so every run outcome can be produced on demand (decision [#16](https://github.com/troupe-run/troupe/issues/16)) |

How to write a runner is in [contributing/runners.md](../contributing/runners.md).
