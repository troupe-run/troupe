# Changelog

## [0.2.0](https://github.com/troupe-run/troupe/compare/troupe-runner-ollama-v0.1.0...troupe-runner-ollama-v0.2.0) (2026-11-20)


### ⚠ BREAKING CHANGES

* **runner-ollama:** troupe-run no longer installs the Ollama runner by default; install troupe-run[ollama] (or troupe-run[all]).
* **runner-protocol:** a runner that predates this rejects run/start's new onContextFull field. The contract is version 0, and every runner is in this repository.
* **runner-protocol:** a runner's result with status error must carry a reason from the contract's list, and an ok result must not; troupe refuses either as a protocol violation, and run.error-result's details now require the reason. Every runner that speaks the contract is in this repository and is updated here; there are no recorded theatres to migrate.
* **runner-protocol:** a Run.Ended outcome with a transcript but no transcriptFormat no longer validates, so ends recorded before this change don't read back (pre-1.0: there are no theatres in use). the OpenAI runner's transcript records are the bytes themselves with the contract's kinds, not its own JSON objects with kind request, response, stream, body or dropped, and the request URL is no longer recorded.

### Features

* **ollama:** a run told to compact stubs old tool results to fit ([30a4a52](https://github.com/troupe-run/troupe/commit/30a4a52cbcff9203574fbeb1531d9317c49887c4))
* **ollama:** end the run with output-limit on a cut answer ([f8a4a86](https://github.com/troupe-run/troupe/commit/f8a4a86e04d4f62a364f58bfe26d789d3046f564))
* **openai:** a run told to compact stubs old outputs after a refusal ([43a2891](https://github.com/troupe-run/troupe/commit/43a28914cff30c7952889317356d09d851cb0047))
* **runner-ollama:** install the Ollama runner as troupe-run[ollama] ([0760a38](https://github.com/troupe-run/troupe/commit/0760a383bdb64680106cfa4fcb83d476cadbf875))
* **runner-ollama:** run troupe's own tool loop over /api/chat ([#277](https://github.com/troupe-run/troupe/issues/277)) ([e2ab0a1](https://github.com/troupe-run/troupe/commit/e2ab0a1572e0d7d1c8ab1c36bb22285cba3b98a0))
* **runner-ollama:** scaffold the plugin and check its options ([#277](https://github.com/troupe-run/troupe/issues/277)) ([0cba57a](https://github.com/troupe-run/troupe/commit/0cba57a88e5ef9a7482c9373c9ae843938b2bdd2))
* **runner-ollama:** take the endpoint and model from the runtime ([ff86f85](https://github.com/troupe-run/troupe/commit/ff86f85add2bbc545f1a47bb25f36595339c99d2)), closes [#289](https://github.com/troupe-run/troupe/issues/289)
* **runner-ollama:** talk to Ollama and check what it requires ([#277](https://github.com/troupe-run/troupe/issues/277)) ([8893bae](https://github.com/troupe-run/troupe/commit/8893baef1b7a6055235fd1a0da79ea59f216d140))
* **runner-ollama:** talk to Ollama through httpx2 ([6c64345](https://github.com/troupe-run/troupe/commit/6c6434522516868dda80b5aa5fe588bff7117fbf))
* **runner-protocol:** a failed result says why, in a reason ([3dcfe3f](https://github.com/troupe-run/troupe/commit/3dcfe3f344d1621109761bedbe5eda5ed773b5a7)), closes [#296](https://github.com/troupe-run/troupe/issues/296)
* **runner-protocol:** report the model that served a run ([409a5f9](https://github.com/troupe-run/troupe/commit/409a5f9c82361e8134d88816010d98e47419defc)), closes [#295](https://github.com/troupe-run/troupe/issues/295)
* **runner-protocol:** run/start says whether the run may compact ([21851c3](https://github.com/troupe-run/troupe/commit/21851c36e6b9e74a5cf7715325580119fe6b8cf1))
* **runner-protocol:** transcript records can say what kind they are ([a0c3fd4](https://github.com/troupe-run/troupe/commit/a0c3fd4d6b13778e4c47833e2cf2c4f062ada922))
* **runners:** end every runner through the SDK's exit_now, so coverage can save ([217e083](https://github.com/troupe-run/troupe/commit/217e083b5bc9d36dea3b2ccc84277e9e20889b9a)), closes [#443](https://github.com/troupe-run/troupe/issues/443)
* **runners:** remove the LM Studio runner before 0.2.0 ([26e9b7a](https://github.com/troupe-run/troupe/commit/26e9b7ac949237f3844a45513473525b63169b75))
* **runtimes:** add an in-process runtime with no endpoint ([3e9ecbd](https://github.com/troupe-run/troupe/commit/3e9ecbdd7e34458cccb6b620b02ae68f87bf6411))


### Bug Fixes

* **config:** keep an old Ollama actor's endpoint in the move's fix ([903f817](https://github.com/troupe-run/troupe/commit/903f8170ab4929eeb82c9bc498b13abfb21aeb0c))
* **runner-ollama:** act on a review of the runner's code ([#277](https://github.com/troupe-run/troupe/issues/277)) ([746b227](https://github.com/troupe-run/troupe/commit/746b227b9bc17ba67e75dc7f5c366c4c1d556a1d))
* **runner-ollama:** count Ollama's cached prompt tokens apart ([292f732](https://github.com/troupe-run/troupe/commit/292f732c5926875ff5a7d8ac736c705513e76d86))
* **runner-ollama:** report cache reads only when every answer does ([fe89f99](https://github.com/troupe-run/troupe/commit/fe89f99e0847f1634fb50e09d47cbd211d97202f))
* **runners:** record each lone surrogate replaced, in a context event ([ae9f7a6](https://github.com/troupe-run/troupe/commit/ae9f7a6f3abe27c9d7863c1f5c56a38b23a64cea))
* **runners:** refuse a second initialize with already-initialized ([ad1769b](https://github.com/troupe-run/troupe/commit/ad1769bd880fbb996b1fc94fafcfdd7aad89923e))
* **runners:** write lone surrogates as U+FFFD, never as an escape ([fef4bd5](https://github.com/troupe-run/troupe/commit/fef4bd5c222b1c13014b8e14bf3692d130624d83))
* **runtimes:** the actor's model beats TROUPE_RUNTIME_&lt;NAME&gt;_MODEL ([782d068](https://github.com/troupe-run/troupe/commit/782d068afe831a98ea6348e54d9a1b06023a76ec))

## 0.1.0 (2026-11-19)


### ⚠ BREAKING CHANGES

* **runner-ollama:** troupe-run no longer installs the Ollama runner by default; install troupe-run[ollama] (or troupe-run[all]).
* **runner-protocol:** a runner that predates this rejects run/start's new onContextFull field. The contract is version 0, and every runner is in this repository.
* **runner-protocol:** a runner's result with status error must carry a reason from the contract's list, and an ok result must not; troupe refuses either as a protocol violation, and run.error-result's details now require the reason. Every runner that speaks the contract is in this repository and is updated here; there are no recorded theatres to migrate.
* **runner-protocol:** a Run.Ended outcome with a transcript but no transcriptFormat no longer validates, so ends recorded before this change don't read back (pre-1.0: there are no theatres in use). the OpenAI runner's transcript records are the bytes themselves with the contract's kinds, not its own JSON objects with kind request, response, stream, body or dropped, and the request URL is no longer recorded.

### Features

* **ollama:** a run told to compact stubs old tool results to fit ([30a4a52](https://github.com/troupe-run/troupe/commit/30a4a52cbcff9203574fbeb1531d9317c49887c4))
* **ollama:** end the run with output-limit on a cut answer ([f8a4a86](https://github.com/troupe-run/troupe/commit/f8a4a86e04d4f62a364f58bfe26d789d3046f564))
* **openai:** a run told to compact stubs old outputs after a refusal ([43a2891](https://github.com/troupe-run/troupe/commit/43a28914cff30c7952889317356d09d851cb0047))
* **runner-ollama:** install the Ollama runner as troupe-run[ollama] ([0760a38](https://github.com/troupe-run/troupe/commit/0760a383bdb64680106cfa4fcb83d476cadbf875))
* **runner-ollama:** run troupe's own tool loop over /api/chat ([#277](https://github.com/troupe-run/troupe/issues/277)) ([e2ab0a1](https://github.com/troupe-run/troupe/commit/e2ab0a1572e0d7d1c8ab1c36bb22285cba3b98a0))
* **runner-ollama:** scaffold the plugin and check its options ([#277](https://github.com/troupe-run/troupe/issues/277)) ([0cba57a](https://github.com/troupe-run/troupe/commit/0cba57a88e5ef9a7482c9373c9ae843938b2bdd2))
* **runner-ollama:** take the endpoint and model from the runtime ([ff86f85](https://github.com/troupe-run/troupe/commit/ff86f85add2bbc545f1a47bb25f36595339c99d2)), closes [#289](https://github.com/troupe-run/troupe/issues/289)
* **runner-ollama:** talk to Ollama and check what it requires ([#277](https://github.com/troupe-run/troupe/issues/277)) ([8893bae](https://github.com/troupe-run/troupe/commit/8893baef1b7a6055235fd1a0da79ea59f216d140))
* **runner-ollama:** talk to Ollama through httpx2 ([6c64345](https://github.com/troupe-run/troupe/commit/6c6434522516868dda80b5aa5fe588bff7117fbf))
* **runner-protocol:** a failed result says why, in a reason ([3dcfe3f](https://github.com/troupe-run/troupe/commit/3dcfe3f344d1621109761bedbe5eda5ed773b5a7)), closes [#296](https://github.com/troupe-run/troupe/issues/296)
* **runner-protocol:** report the model that served a run ([409a5f9](https://github.com/troupe-run/troupe/commit/409a5f9c82361e8134d88816010d98e47419defc)), closes [#295](https://github.com/troupe-run/troupe/issues/295)
* **runner-protocol:** run/start says whether the run may compact ([21851c3](https://github.com/troupe-run/troupe/commit/21851c36e6b9e74a5cf7715325580119fe6b8cf1))
* **runner-protocol:** transcript records can say what kind they are ([a0c3fd4](https://github.com/troupe-run/troupe/commit/a0c3fd4d6b13778e4c47833e2cf2c4f062ada922))
* **runners:** end every runner through the SDK's exit_now, so coverage can save ([217e083](https://github.com/troupe-run/troupe/commit/217e083b5bc9d36dea3b2ccc84277e9e20889b9a)), closes [#443](https://github.com/troupe-run/troupe/issues/443)
* **runners:** remove the LM Studio runner before 0.2.0 ([26e9b7a](https://github.com/troupe-run/troupe/commit/26e9b7ac949237f3844a45513473525b63169b75))
* **runtimes:** add an in-process runtime with no endpoint ([3e9ecbd](https://github.com/troupe-run/troupe/commit/3e9ecbdd7e34458cccb6b620b02ae68f87bf6411))


### Bug Fixes

* **config:** keep an old Ollama actor's endpoint in the move's fix ([903f817](https://github.com/troupe-run/troupe/commit/903f8170ab4929eeb82c9bc498b13abfb21aeb0c))
* **runner-ollama:** act on a review of the runner's code ([#277](https://github.com/troupe-run/troupe/issues/277)) ([746b227](https://github.com/troupe-run/troupe/commit/746b227b9bc17ba67e75dc7f5c366c4c1d556a1d))
* **runner-ollama:** count Ollama's cached prompt tokens apart ([292f732](https://github.com/troupe-run/troupe/commit/292f732c5926875ff5a7d8ac736c705513e76d86))
* **runner-ollama:** report cache reads only when every answer does ([fe89f99](https://github.com/troupe-run/troupe/commit/fe89f99e0847f1634fb50e09d47cbd211d97202f))
* **runners:** record each lone surrogate replaced, in a context event ([ae9f7a6](https://github.com/troupe-run/troupe/commit/ae9f7a6f3abe27c9d7863c1f5c56a38b23a64cea))
* **runners:** refuse a second initialize with already-initialized ([ad1769b](https://github.com/troupe-run/troupe/commit/ad1769bd880fbb996b1fc94fafcfdd7aad89923e))
* **runners:** write lone surrogates as U+FFFD, never as an escape ([fef4bd5](https://github.com/troupe-run/troupe/commit/fef4bd5c222b1c13014b8e14bf3692d130624d83))
* **runtimes:** the actor's model beats TROUPE_RUNTIME_&lt;NAME&gt;_MODEL ([782d068](https://github.com/troupe-run/troupe/commit/782d068afe831a98ea6348e54d9a1b06023a76ec))
