# Changelog

## [0.2.0](https://github.com/troupe-run/troupe/compare/troupe-plugin-sdk-v0.1.0...troupe-plugin-sdk-v0.2.0) (2026-11-24)


### Features

* **protocol:** let a runtime name the engine that serves it ([f0b126f](https://github.com/troupe-run/troupe/commit/f0b126f48ead3842b8f88ef34986f839a95c1fd4))

## 0.1.0 (2026-11-19)


### ⚠ BREAKING CHANGES

* **sdk:** EventNumbering requires send_context.
* **runner-protocol:** a runner that predates this rejects run/start's new onContextFull field. The contract is version 0, and every runner is in this repository.
* **runner-protocol:** say when a retry wasn't safe
* **protocol:** records and messages that leave out these fields, or hold runner_reported or a start's clones, no longer validate.
* **runner-protocol:** a runner's result with status error must carry a reason from the contract's list, and an ok result must not; troupe refuses either as a protocol violation, and run.error-result's details now require the reason. Every runner that speaks the contract is in this repository and is updated here; there are no recorded theatres to migrate.
* **runner-protocol:** a Run.Ended outcome with a transcript but no transcriptFormat no longer validates, so ends recorded before this change don't read back (pre-1.0: there are no theatres in use). the OpenAI runner's transcript records are the bytes themselves with the contract's kinds, not its own JSON objects with kind request, response, stream, body or dropped, and the request URL is no longer recorded.

### Features

* carry declared effects and a scratch directory to runners ([ce62005](https://github.com/troupe-run/troupe/commit/ce6200565f60b7a1b6661f2061aa7994cedb7d86))
* **plugin-sdk:** define what a credential's value may hold, once ([d97ce8f](https://github.com/troupe-run/troupe/commit/d97ce8f109d062215c690f93a8cffbf3e1b82516))
* **protocol:** estimate a run's cost from a price troupe resolves ([b809b61](https://github.com/troupe-run/troupe/commit/b809b61b451cd5aeac6154eaa0cd16ab8f5b4ba9))
* **protocol:** require the fields troupe always writes ([1222e08](https://github.com/troupe-run/troupe/commit/1222e08981ebc1c06d978a5f200c5ff670b71726)), closes [#305](https://github.com/troupe-run/troupe/issues/305)
* **runner-ollama:** talk to Ollama and check what it requires ([#277](https://github.com/troupe-run/troupe/issues/277)) ([8893bae](https://github.com/troupe-run/troupe/commit/8893baef1b7a6055235fd1a0da79ea59f216d140))
* **runner-protocol:** a context event for content lost mid-run ([66a0127](https://github.com/troupe-run/troupe/commit/66a012776a1b8aa37ff544397b9d5096b6ef63ce))
* **runner-protocol:** a failed result says why, in a reason ([3dcfe3f](https://github.com/troupe-run/troupe/commit/3dcfe3f344d1621109761bedbe5eda5ed773b5a7)), closes [#296](https://github.com/troupe-run/troupe/issues/296)
* **runner-protocol:** report the model that served a run ([409a5f9](https://github.com/troupe-run/troupe/commit/409a5f9c82361e8134d88816010d98e47419defc)), closes [#295](https://github.com/troupe-run/troupe/issues/295)
* **runner-protocol:** run/start says whether the run may compact ([21851c3](https://github.com/troupe-run/troupe/commit/21851c36e6b9e74a5cf7715325580119fe6b8cf1))
* **runner-protocol:** say when a retry wasn't safe ([0dda581](https://github.com/troupe-run/troupe/commit/0dda58103d34b1aece6cf01c9c8636776dd36168)), closes [#378](https://github.com/troupe-run/troupe/issues/378)
* **runner-protocol:** transcript records can say what kind they are ([a0c3fd4](https://github.com/troupe-run/troupe/commit/a0c3fd4d6b13778e4c47833e2cf2c4f062ada922))
* **runners:** end every runner through the SDK's exit_now, so coverage can save ([217e083](https://github.com/troupe-run/troupe/commit/217e083b5bc9d36dea3b2ccc84277e9e20889b9a)), closes [#443](https://github.com/troupe-run/troupe/issues/443)
* **runners:** remove the LM Studio runner before 0.2.0 ([26e9b7a](https://github.com/troupe-run/troupe/commit/26e9b7ac949237f3844a45513473525b63169b75))
* **runtimes:** add an in-process runtime with no endpoint ([3e9ecbd](https://github.com/troupe-run/troupe/commit/3e9ecbdd7e34458cccb6b620b02ae68f87bf6411))
* **runtimes:** name runtimes in config and hand runs their credential ([5e14751](https://github.com/troupe-run/troupe/commit/5e14751ac70c364326dedd44a2e6b8c8186cb05c))
* **sdk:** check tool paths and declared effects ([3a38e7b](https://github.com/troupe-run/troupe/commit/3a38e7ba4a83a50efbca1799df79f2391b610345))
* **sdk:** require send_context to build an EventNumbering ([f172a1a](https://github.com/troupe-run/troupe/commit/f172a1a560b491fa4b5a974dcfb46b30f387c6e5))
* **sdk:** run a model's tool calls in the workspace ([e415af7](https://github.com/troupe-run/troupe/commit/e415af71dbbaf97e2a7e5c8cd8b362a60067a3f1))


### Bug Fixes

* **config:** never name the keys leading to a null in a value ([e6710ab](https://github.com/troupe-run/troupe/commit/e6710aba13d319f14e4922f2d629db9435753ba5))
* **config:** never repeat a value core refuses for its shape ([b5a95bd](https://github.com/troupe-run/troupe/commit/b5a95bd9155a76acc3953d42501d0800163f5288))
* **host:** parse a runner's line before masking it ([14245f6](https://github.com/troupe-run/troupe/commit/14245f620ae341248e1df7a7f961d6a2dbe992d0))
* **runner-protocol:** say usage.inputTokens leaves out cache tokens ([f6d80b5](https://github.com/troupe-run/troupe/commit/f6d80b50f51845773243bcf22ebbfadbbc985da5))
* **runners:** clean a tool call's id and OpenAI's non-stream body ([45ab433](https://github.com/troupe-run/troupe/commit/45ab433c4f9fd08ee3c0b2d8c21c5e4dd229381f))
* **runners:** record each lone surrogate replaced, in a context event ([ae9f7a6](https://github.com/troupe-run/troupe/commit/ae9f7a6f3abe27c9d7863c1f5c56a38b23a64cea))
* **runners:** refuse a second initialize with already-initialized ([ad1769b](https://github.com/troupe-run/troupe/commit/ad1769bd880fbb996b1fc94fafcfdd7aad89923e))
* **runners:** write lone surrogates as U+FFFD, never as an escape ([fef4bd5](https://github.com/troupe-run/troupe/commit/fef4bd5c222b1c13014b8e14bf3692d130624d83))
* **sdk:** clean a tool call's input after parsing its JSON text ([276374b](https://github.com/troupe-run/troupe/commit/276374bbe1ae6218053f3347bcbae08c92647bd7))
* **sdk:** give a path outside scratch the same answer everywhere ([130b91e](https://github.com/troupe-run/troupe/commit/130b91e1812e535f70f4bae369d4fe2016386164))
* **sdk:** load only regular files of a bounded size ([c70a494](https://github.com/troupe-run/troupe/commit/c70a494d8de6b3146fe99e3b99fcfa1fde364959))
* **sdk:** never repeat an endpoint refused in run/start ([8619164](https://github.com/troupe-run/troupe/commit/8619164f89eaccaa594c0e9ada5b3eded280ebda))
* **sdk:** never search through a Windows junction out of the workspace ([855a3bf](https://github.com/troupe-run/troupe/commit/855a3bf5f22bfd42f86b1e8358b543c2d738b479))
* **sdk:** one context event per place; bound run_with_progress ([acea07a](https://github.com/troupe-run/troupe/commit/acea07aaa8a858f74b347c64fc1c2055540d01a1))
* **sdk:** refuse a credential a request header can't carry ([b691e3f](https://github.com/troupe-run/troupe/commit/b691e3fe59177461d02de09fed6fff85329b81d9))
* **sdk:** walk messages for lone surrogates without recursion ([79800e2](https://github.com/troupe-run/troupe/commit/79800e2da2777ce65cad058e86c2278cb461be6f))
