---
title: Changelog
description: What changed in each release.
status: written
prerelease: false
---

Each part of troupe that's released has its own changelog, written by
[release-please](https://github.com/googleapis/release-please) from the commits on troupe's `main`. Nobody edits
them by hand, and a release's notes on GitHub are its changelog section. A change shows up in the changelog of the
part it touched, grouped by kind: breaking changes first, then **Features**, **Bug Fixes**, **Performance
Improvements** and **Reverts**. Changes to troupe's own docs, tests and tooling aren't listed.

Until 1.0, every release is marked **Pre-release** on GitHub: troupe makes no promise of stability before 1.0.

## troupe

Each part releases on its own, at its own version, when it changes: the core, each bundled adapter and each runner.
`troupe-run`, the package you install, follows: after any of them releases, a new `troupe-run` pins that release, and
its version moves by the largest change it now ships. Its changelog lists those, and each part's changelog says what
changed in it.

- [troupe](https://github.com/troupe-run/troupe/blob/main/packages/troupe/CHANGELOG.md)
- [troupe-artifacts-local](https://github.com/troupe-run/troupe/blob/main/packages/troupe-artifacts-local/CHANGELOG.md)
- [troupe-identity-local](https://github.com/troupe-run/troupe/blob/main/packages/troupe-identity-local/CHANGELOG.md)
- [troupe-run](https://github.com/troupe-run/troupe/blob/main/packages/troupe-run/CHANGELOG.md), the package you install
- [troupe-stage-local](https://github.com/troupe-run/troupe/blob/main/packages/troupe-stage-local/CHANGELOG.md)
- [troupe-store-text](https://github.com/troupe-run/troupe/blob/main/packages/troupe-store-text/CHANGELOG.md)
- [troupe-vcs-files](https://github.com/troupe-run/troupe/blob/main/packages/troupe-vcs-files/CHANGELOG.md)
- [troupe-vcs-git](https://github.com/troupe-run/troupe/blob/main/packages/troupe-vcs-git/CHANGELOG.md)

## Protocol

The protocol, the contracts troupe and its plugins speak, is released on its own, at its own version, only when it
changes. `troupe --version` names the protocol version that troupe carries.

- [protocol](https://github.com/troupe-run/troupe/blob/main/protocol/CHANGELOG.md)

## Plugins

The runners are released on their own, like the other parts, and `troupe-run` ships each release.

- `troupe-runner-anthropic`
- [troupe-runner-claude-code](https://github.com/troupe-run/troupe/blob/main/plugins/runner-claude-code/CHANGELOG.md)
- `troupe-runner-ollama`
- `troupe-runner-openai`
- [troupe-runner-scripted](https://github.com/troupe-run/troupe/blob/main/plugins/runner-scripted/CHANGELOG.md)

The Anthropic, Ollama and OpenAI runners' changelogs start with their first releases, and are linked here once they
exist.

The plugin SDK, the library the runners and the core share for the runner contract, is released on its own too. Its
changelog starts with its first release, and is linked here once it exists.

- `troupe-plugin-sdk`

Every release is also on [GitHub's releases page](https://github.com/troupe-run/troupe/releases).
