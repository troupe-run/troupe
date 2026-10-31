---
title: Changelog
description: What changed in each release.
status: written
prerelease: false
---

Each part of troupe that's released has its own changelog, written by
[release-please](https://github.com/googleapis/release-please) from the commits on troupe's `main`. Nobody edits
them by hand, and a release's notes on GitHub are its changelog section. A change shows up in the changelog of the
part it touched, grouped by kind: for example, features under **Features** and fixes under **Bug Fixes**.

## troupe

Everything `troupe-run` installs releases together, at one version: the core, its bundled adapters and the runners.
When any of them changes, all of them release. The core's changelog is the one to read for what changed in troupe as
a whole. The others list the changes that touched them.

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

The runners are released with troupe, at the same version.

- [troupe-runner-claude-code](https://github.com/troupe-run/troupe/blob/main/plugins/runner-claude-code/CHANGELOG.md)
- [troupe-runner-scripted](https://github.com/troupe-run/troupe/blob/main/plugins/runner-scripted/CHANGELOG.md)

Every release is also on [GitHub's releases page](https://github.com/troupe-run/troupe/releases).
