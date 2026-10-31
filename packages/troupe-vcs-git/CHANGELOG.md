# Changelog

## 0.1.0 (2026-10-31)


### ⚠ BREAKING CHANGES

* **runners:** the runner contract is version 0, the draft
* **protocol:** error and notice detail keys that were snake_case are now camelCase (exitCode, limitBytes, waitedSeconds and the rest), and events.unknown-format's format detail is JSON text. Nothing outside this repository reads them.

### Features

* **config:** project config to files under .troupe/, replacing only the files troupe wrote ([#60](https://github.com/troupe-run/troupe/issues/60)) ([e2ac5c1](https://github.com/troupe-run/troupe/commit/e2ac5c1693bcac370fa7e5d0c6560f70456f5fa2))
* **protocol:** catalogue every error and notice code with closed details ([36f8241](https://github.com/troupe-run/troupe/commit/36f824164ede66cba5128ab7f79c2fb25a7af7c0))
* **runners:** the runner contract is version 0, the draft ([69d6c27](https://github.com/troupe-run/troupe/commit/69d6c276db144bd47bdfb39e69d2ac3e03bc6144))
* **vcs:** cache the branch and HEAD behind a token that sees every move ([#75](https://github.com/troupe-run/troupe/issues/75)) ([cceeee4](https://github.com/troupe-run/troupe/commit/cceeee41e40d618031ef6818922977bf1d4d0b72))
* **vcs:** make, fill, diff, apply and remove a run's worktree, and snapshot shared git state ([#51](https://github.com/troupe-run/troupe/issues/51)) ([6ba3ac5](https://github.com/troupe-run/troupe/commit/6ba3ac5c3381014ba7abe5c2b5ee1b77729885cc))
* **vcs:** mark a merged path resolved through the VCS port ([eabe7a1](https://github.com/troupe-run/troupe/commit/eabe7a12eccaba026fd7b8af1fb2268cb2747590))
* **vcs:** read branch, HEAD and what is committed through a VCS port ([4729252](https://github.com/troupe-run/troupe/commit/4729252008441c7fe66abb20330ca8e9f8f1e686))
* **vcs:** read the branch and HEAD again just after a change ([#75](https://github.com/troupe-run/troupe/issues/75)) ([54d9a94](https://github.com/troupe-run/troupe/commit/54d9a941dfe8c207d687522e3d31be30262a2d6e))
* **vcs:** report the sides a merge combined into a path ([#141](https://github.com/troupe-run/troupe/issues/141)) ([dbc699f](https://github.com/troupe-run/troupe/commit/dbc699f0c3043e07e65f5a110e948e899016f63d))
* **workspace:** add the event-store adapter packages and their import contracts ([6746785](https://github.com/troupe-run/troupe/commit/67467850696f4da6df5330c47e78133cdae4a38f))


### Bug Fixes

* **runs:** reload a run whose Run.WorktreeMade couldn't be recorded ([dd6189b](https://github.com/troupe-run/troupe/commit/dd6189bc719b2a85b119c43b5c047efe2b598490))
* **vcs:** don't refuse a theatre whose commit holds a file git would normalise ([#51](https://github.com/troupe-run/troupe/issues/51)) ([526682b](https://github.com/troupe-run/troupe/commit/526682b9e0d9425960d795a0ac8dc45d6f8d1caa))
* **vcs:** mark a path that holds only its base stage resolved ([0b69d7c](https://github.com/troupe-run/troupe/commit/0b69d7cc460d45f1f229144c77c4eb7cb27c88a3))


### Documentation

* move the contributor docs to contributing/ ([296599d](https://github.com/troupe-run/troupe/commit/296599dbfb5893db05dae8c6ab7ec89518b3befb)), closes [#123](https://github.com/troupe-run/troupe/issues/123)
