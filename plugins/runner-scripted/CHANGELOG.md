# Changelog

## [0.2.0](https://github.com/troupe-run/troupe/compare/troupe-runner-scripted-v0.1.0...troupe-runner-scripted-v0.2.0) (2026-11-14)


### ⚠ BREAKING CHANGES

* **runner-protocol:** a runner that predates this rejects run/start's new onContextFull field. The contract is version 0, and every runner is in this repository.
* **runner-protocol:** say when a retry wasn't safe
* **runner-protocol:** a runner's result with status error must carry a reason from the contract's list, and an ok result must not; troupe refuses either as a protocol violation, and run.error-result's details now require the reason. Every runner that speaks the contract is in this repository and is updated here; there are no recorded theatres to migrate.
* **runner-protocol:** a Run.Ended outcome with a transcript but no transcriptFormat no longer validates, so ends recorded before this change don't read back (pre-1.0: there are no theatres in use). the OpenAI runner's transcript records are the bytes themselves with the contract's kinds, not its own JSON objects with kind request, response, stream, body or dropped, and the request URL is no longer recorded.

### Features

* carry declared effects and a scratch directory to runners ([ce62005](https://github.com/troupe-run/troupe/commit/ce6200565f60b7a1b6661f2061aa7994cedb7d86))
* **protocol:** estimate a run's cost from a price troupe resolves ([b809b61](https://github.com/troupe-run/troupe/commit/b809b61b451cd5aeac6154eaa0cd16ab8f5b4ba9))
* **runner-protocol:** a context event for content lost mid-run ([66a0127](https://github.com/troupe-run/troupe/commit/66a012776a1b8aa37ff544397b9d5096b6ef63ce))
* **runner-protocol:** a failed result says why, in a reason ([3dcfe3f](https://github.com/troupe-run/troupe/commit/3dcfe3f344d1621109761bedbe5eda5ed773b5a7)), closes [#296](https://github.com/troupe-run/troupe/issues/296)
* **runner-protocol:** report the model that served a run ([409a5f9](https://github.com/troupe-run/troupe/commit/409a5f9c82361e8134d88816010d98e47419defc)), closes [#295](https://github.com/troupe-run/troupe/issues/295)
* **runner-protocol:** run/start says whether the run may compact ([21851c3](https://github.com/troupe-run/troupe/commit/21851c36e6b9e74a5cf7715325580119fe6b8cf1))
* **runner-protocol:** say when a retry wasn't safe ([0dda581](https://github.com/troupe-run/troupe/commit/0dda58103d34b1aece6cf01c9c8636776dd36168)), closes [#378](https://github.com/troupe-run/troupe/issues/378)
* **runner-protocol:** transcript records can say what kind they are ([a0c3fd4](https://github.com/troupe-run/troupe/commit/a0c3fd4d6b13778e4c47833e2cf2c4f062ada922))
* **runtimes:** name runtimes in config and hand runs their credential ([5e14751](https://github.com/troupe-run/troupe/commit/5e14751ac70c364326dedd44a2e6b8c8186cb05c))
* **scripted:** a tool step that runs calls through the SDK's tools ([949996a](https://github.com/troupe-run/troupe/commit/949996a22aeaa537ab821abebb752af75c74c5d5))


### Bug Fixes

* **runner-protocol:** act on the slice reviews of record kinds ([87d51d8](https://github.com/troupe-run/troupe/commit/87d51d83149f7547852f81721a84a2e9d627daef)), closes [#294](https://github.com/troupe-run/troupe/issues/294)

## 0.1.0 (2026-11-01)


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
