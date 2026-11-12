# Proposal

## Why

Dependabot's #343 updates pycryptodome from 3.24.1 to 4.2.0. It's a major update, so the guard's
`commit-branch-change` refuses Dependabot's branch, and the update needs an OpenSpec change of its own (#250;
development-workflow, "Dependabot pull requests"). 4.0.0 ("Grenoble") has breaking changes, so each use has to be
checked against them before the update lands.

## What Changes

- The root `pyproject.toml`'s dev group requires `pycryptodome>=4.2.0` (was `>=3.23`), the same line Dependabot's
  #343 changes, and `uv.lock` resolves it to 4.2.0.
- No other file changes. troupe's own code, tests and scripts never import `Crypto` or `Cryptodome`. The one use is
  `eventsourcing.cipher.AESCipher`, which `eventsourcing.tests.persistence` imports at module scope. troupe-store-text's
  `test_library_suite.py` runs that suite, including its two cipher cases. Every name `AESCipher` uses still works in
  4.2.0, and none of 4.0.0's breaking changes reaches it (design D1).
- The comment above the line is kept: it already says why the dependency is there.

No product behaviour changes, and pycryptodome isn't a runtime dependency of any package, so no spec changes
(`skip_specs: true`). The event-store spec's "The store meets the library's recorder contract" holds as it is: the
full check runs that suite against 4.2.0.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None.

## Impact

- `pyproject.toml` (one line) and `uv.lock` (pycryptodome's entry and the dev group's specifier).
- Dev environments and CI legs install pycryptodome 4.2.0. Its wheels are `cp39-abi3` for Linux (manylinux and
  musllinux), macOS and Windows, which covers CI's matrix of CPython 3.12 to 3.15 on all three systems.
- No release: pycryptodome is a dev dependency of the workspace root, so no package's files change.
- Closes troupe-run/troupe#250. Dependabot's #343 is closed with a link to this change's pull request once that pull
  request has merged (design D3).
