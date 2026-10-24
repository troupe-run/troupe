# Changelog

## 0.1.0 (2026-10-24)


### ⚠ BREAKING CHANGES

* **runners:** the runner contract is version 0, the draft
* **runner-protocol:** a run event carrying native is a protocol violation. Only this repository's scripted runner and fixtures used it.

### Features

* **plugins:** add the scripted runner ([297fd72](https://github.com/troupe-run/troupe/commit/297fd7281ff7880549c5ceae3d53d354e87e7a07))
* **protocol:** mark the JSON-RPC error id as the one null ([5244b9a](https://github.com/troupe-run/troupe/commit/5244b9afdf440bd42c48f8841513b90715b0636b)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
* **runner-protocol:** close run events, results and runner errors ([613ca5b](https://github.com/troupe-run/troupe/commit/613ca5bfc2f7af4519adb47f98d9a50c6826e0db))
* **runner-protocol:** runner options are an extension point the runner fills ([84b46c3](https://github.com/troupe-run/troupe/commit/84b46c3e251cfcf29e1702fc77bcb00e02760d04))
* **runner:** run/start carries the run's direction and the actor's character ([#60](https://github.com/troupe-run/troupe/issues/60)) ([7eece31](https://github.com/troupe-run/troupe/commit/7eece31b55367f2ec6b7a2b022b2aeffed361500))
* **runners:** the runner contract is version 0, the draft ([69d6c27](https://github.com/troupe-run/troupe/commit/69d6c276db144bd47bdfb39e69d2ac3e03bc6144))
* **schemas:** troupe carries the protocol's schemas, and reads a runner's from the installed runner ([#60](https://github.com/troupe-run/troupe/issues/60)) ([5ea49b2](https://github.com/troupe-run/troupe/commit/5ea49b24d218e5c0c7ebbb849dbab45a6f7950d0))
* **scripts:** declare which paths need which part of the check ([e9f7db5](https://github.com/troupe-run/troupe/commit/e9f7db51ac9395253c9752815a8d85621431e7e8))


### Bug Fixes

* **runner-scripted:** play a script's instant steps before answering troupe ([0e6ac17](https://github.com/troupe-run/troupe/commit/0e6ac17f45daa5038555f38d5794e4e61ac0e212))


### Documentation

* move the contributor docs to contributing/ ([296599d](https://github.com/troupe-run/troupe/commit/296599dbfb5893db05dae8c6ab7ec89518b3befb)), closes [#123](https://github.com/troupe-run/troupe/issues/123)
* **openspec:** archive omit-nulls and sync its specs ([31ccdfe](https://github.com/troupe-run/troupe/commit/31ccdfe80c331e316b6c72c166a159cd61357e3c)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
