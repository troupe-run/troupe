# Changelog

## 0.1.0 (2026-10-17)


### ⚠ BREAKING CHANGES

* **runners:** the runner contract is version 0, the draft
* **runner-protocol:** a run event carrying native is a protocol violation. Only this repository's scripted runner and fixtures used it.

### Features

* **plugins:** add the scripted runner ([297fd72](https://github.com/troupe-run/troupe/commit/297fd7281ff7880549c5ceae3d53d354e87e7a07))
* **protocol:** mark the JSON-RPC error id as the one null ([5244b9a](https://github.com/troupe-run/troupe/commit/5244b9afdf440bd42c48f8841513b90715b0636b)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
* **runner-protocol:** close run events, results and runner errors ([613ca5b](https://github.com/troupe-run/troupe/commit/613ca5bfc2f7af4519adb47f98d9a50c6826e0db))
* **runner-protocol:** runner options are an extension point the runner fills ([84b46c3](https://github.com/troupe-run/troupe/commit/84b46c3e251cfcf29e1702fc77bcb00e02760d04))
* **runners:** the runner contract is version 0, the draft ([69d6c27](https://github.com/troupe-run/troupe/commit/69d6c276db144bd47bdfb39e69d2ac3e03bc6144))
* **scripts:** declare which paths need which part of the check ([e9f7db5](https://github.com/troupe-run/troupe/commit/e9f7db51ac9395253c9752815a8d85621431e7e8))


### Bug Fixes

* **runner-scripted:** play a script's instant steps before answering troupe ([0e6ac17](https://github.com/troupe-run/troupe/commit/0e6ac17f45daa5038555f38d5794e4e61ac0e212))
