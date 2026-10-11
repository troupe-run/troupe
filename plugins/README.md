# plugins

Out-of-process plugins: actor runners, stages, guests and notification channels. **Third-party code only ever
runs out of process**, so that declared effects can be enforced on it and a plugin can be written in any
language.

Rules for everything in this directory:

- **A plugin is a separate process** that troupe starts and talks to with JSON-RPC over stdio. The messages are
  defined in [`protocol/`](../protocol/). A containerised plugin is the same thing, run inside `docker run`.
- **A plugin imports only the protocol, never `troupe`.** It sees troupe exactly as a third party would, so
  first-party plugins prove the contract is complete. This is enforced by an import-linter contract, added with
  the first plugin.
- **Each plugin is self-contained:** its own `pyproject.toml` (or its language's equivalent), tests and, where it
  needs one, a container image. That lets it move to its own repository later with its history
  (`git filter-repo`).

First-party *in-process* adapters (storage, version control, built-in identity sources) are not plugins. They
live under [`packages/`](../packages/), because they sit deep in the house and are loaded as Python packages.

The first plugin, a scripted actor runner for deterministic tests, arrives with the walking skeleton (decision
[#16](https://github.com/troupe-run/troupe/issues/16)).
