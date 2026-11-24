## [0.2.0](https://github.com/troupe-run/troupe/compare/troupe-runner-scripted-v0.1.0...troupe-runner-scripted-v0.2.0) (2026-11-20)


### � BREAKING CHANGES

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
* **runners:** end every runner through the SDK's exit_now, so coverage can save ([217e083](https://github.com/troupe-run/troupe/commit/217e083b5bc9d36dea3b2ccc84277e9e20889b9a)), closes [#443](https://github.com/troupe-run/troupe/issues/443)
* **runtimes:** name runtimes in config and hand runs their credential ([5e14751](https://github.com/troupe-run/troupe/commit/5e14751ac70c364326dedd44a2e6b8c8186cb05c))
* **scripted:** a tool step that runs calls through the SDK's tools ([949996a](https://github.com/troupe-run/troupe/commit/949996a22aeaa537ab821abebb752af75c74c5d5))


### Bug Fixes

* **runner-protocol:** act on the slice reviews of record kinds ([87d51d8](https://github.com/troupe-run/troupe/commit/87d51d83149f7547852f81721a84a2e9d627daef)), closes [#294](https://github.com/troupe-run/troupe/issues/294)
* **runners:** record each lone surrogate replaced, in a context event ([ae9f7a6](https://github.com/troupe-run/troupe/commit/ae9f7a6f3abe27c9d7863c1f5c56a38b23a64cea))
* **runners:** refuse a second initialize with already-initialized ([ad1769b](https://github.com/troupe-run/troupe/commit/ad1769bd880fbb996b1fc94fafcfdd7aad89923e))
* **runners:** write lone surrogates as U+FFFD, never as an escape ([fef4bd5](https://github.com/troupe-run/troupe/commit/fef4bd5c222b1c13014b8e14bf3692d130624d83))