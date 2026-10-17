# Changelog

## 0.1.0 (2026-10-17)


### ⚠ BREAKING CHANGES

* **protocol:** error and notice detail keys that were snake_case are now camelCase (exitCode, limitBytes, waitedSeconds and the rest), and events.unknown-format's format detail is JSON text. Nothing outside this repository reads them.

### Features

* **protocol:** catalogue every error and notice code with closed details ([36f8241](https://github.com/troupe-run/troupe/commit/36f824164ede66cba5128ab7f79c2fb25a7af7c0))
* **vcs:** read branch, HEAD and what is committed through a VCS port ([4729252](https://github.com/troupe-run/troupe/commit/4729252008441c7fe66abb20330ca8e9f8f1e686))
* **workspace:** add the event-store adapter packages and their import contracts ([6746785](https://github.com/troupe-run/troupe/commit/67467850696f4da6df5330c47e78133cdae4a38f))
