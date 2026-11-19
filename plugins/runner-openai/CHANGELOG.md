# Changelog

## 0.1.0 (2026-11-19)


### ⚠ BREAKING CHANGES

* **openai:** the OpenAI runner is troupe-run's openai extra, no longer in the base install; install troupe-run[openai] or [all].
* **sdk:** EventNumbering requires send_context.
* **runner-protocol:** a runner that predates this rejects run/start's new onContextFull field. The contract is version 0, and every runner is in this repository.
* **runner-protocol:** a runner's result with status error must carry a reason from the contract's list, and an ok result must not; troupe refuses either as a protocol violation, and run.error-result's details now require the reason. Every runner that speaks the contract is in this repository and is updated here; there are no recorded theatres to migrate.
* **runner-protocol:** a Run.Ended outcome with a transcript but no transcriptFormat no longer validates, so ends recorded before this change don't read back (pre-1.0: there are no theatres in use). the OpenAI runner's transcript records are the bytes themselves with the contract's kinds, not its own JSON objects with kind request, response, stream, body or dropped, and the request URL is no longer recorded.

### Features

* **config:** refuse an actor whose runner can't use its runtime ([ed15536](https://github.com/troupe-run/troupe/commit/ed1553634db7689202f6bd9bda6467aba1c89a5f))
* **openai:** a run told to compact stubs old outputs after a refusal ([43a2891](https://github.com/troupe-run/troupe/commit/43a28914cff30c7952889317356d09d851cb0047))
* **openai:** send the OpenAI runner's requests through openai ([3a732a3](https://github.com/troupe-run/troupe/commit/3a732a38830a9f934ca0941d9038e62fa689667c)), closes [#331](https://github.com/troupe-run/troupe/issues/331)
* **plugin-sdk:** define what a credential's value may hold, once ([d97ce8f](https://github.com/troupe-run/troupe/commit/d97ce8f109d062215c690f93a8cffbf3e1b82516))
* **runner-openai:** estimate a run's cost from troupe's price ([5307f14](https://github.com/troupe-run/troupe/commit/5307f147e9aeb7e994ad8b7a655408c376edf9f1))
* **runner-openai:** rename to openai, ship it, and give it an audition ([f4cedac](https://github.com/troupe-run/troupe/commit/f4cedac9f3ce3e90af0b397c62a4910be6f3b997))
* **runner-openai:** speak the Responses API ([321699d](https://github.com/troupe-run/troupe/commit/321699d2f67e2cc2c51f530b9bd1a1406521661d))
* **runner-protocol:** a failed result says why, in a reason ([3dcfe3f](https://github.com/troupe-run/troupe/commit/3dcfe3f344d1621109761bedbe5eda5ed773b5a7)), closes [#296](https://github.com/troupe-run/troupe/issues/296)
* **runner-protocol:** report the model that served a run ([409a5f9](https://github.com/troupe-run/troupe/commit/409a5f9c82361e8134d88816010d98e47419defc)), closes [#295](https://github.com/troupe-run/troupe/issues/295)
* **runner-protocol:** run/start says whether the run may compact ([21851c3](https://github.com/troupe-run/troupe/commit/21851c36e6b9e74a5cf7715325580119fe6b8cf1))
* **runner-protocol:** transcript records can say what kind they are ([a0c3fd4](https://github.com/troupe-run/troupe/commit/a0c3fd4d6b13778e4c47833e2cf2c4f062ada922))
* **runners:** end every runner through the SDK's exit_now, so coverage can save ([217e083](https://github.com/troupe-run/troupe/commit/217e083b5bc9d36dea3b2ccc84277e9e20889b9a)), closes [#443](https://github.com/troupe-run/troupe/issues/443)
* **runtimes:** add an in-process runtime with no endpoint ([3e9ecbd](https://github.com/troupe-run/troupe/commit/3e9ecbdd7e34458cccb6b620b02ae68f87bf6411))
* **runtimes:** refuse a credential holding whitespace in core ([cac94eb](https://github.com/troupe-run/troupe/commit/cac94ebbed4a886a4aaf4119b16c5e9f9a015df9))
* **sdk:** require send_context to build an EventNumbering ([f172a1a](https://github.com/troupe-run/troupe/commit/f172a1a560b491fa4b5a974dcfb46b30f387c6e5))


### Bug Fixes

* **claude-code:** note a replaced surrogate in the effects server ([96bc001](https://github.com/troupe-run/troupe/commit/96bc00102f8478f4d7c0b528bf46716ff58e912b))
* **openai:** keep an encoded error's status; close events at once ([de5b095](https://github.com/troupe-run/troupe/commit/de5b0958e6ee07a4895371fbef37587a225d623e)), closes [#331](https://github.com/troupe-run/troupe/issues/331)
* **openai:** keep requests below an endpoint whose path is // ([1f85a18](https://github.com/troupe-run/troupe/commit/1f85a18fb7ed4d4ea54bd0081d9067581bcf98da))
* **openai:** load the openai package only after run/start ([8ca2770](https://github.com/troupe-run/troupe/commit/8ca27705a3dc3e42dd66491b1db304c96380709a)), closes [#331](https://github.com/troupe-run/troupe/issues/331)
* **openai:** refuse an encoded response the line cap can't count ([e87bcc8](https://github.com/troupe-run/troupe/commit/e87bcc8dc8a76e2be5765c3cffcbb25e5c5e5c2c)), closes [#331](https://github.com/troupe-run/troupe/issues/331)
* **openai:** send only the headers a request needs ([1102fb0](https://github.com/troupe-run/troupe/commit/1102fb061e1695e45a8f1796778edbf52b3687b9)), closes [#331](https://github.com/troupe-run/troupe/issues/331)
* **openai:** stop reading a whole body at ERROR_BODY_MAX_BYTES ([e646c37](https://github.com/troupe-run/troupe/commit/e646c379567b31f2e410d84b8d90719608832bd7)), closes [#331](https://github.com/troupe-run/troupe/issues/331)
* **runner-openai:** act on an independent review of unread files ([a00c1aa](https://github.com/troupe-run/troupe/commit/a00c1aa509c357ac3a662e92b3cd61a4f181ef22))
* **runner-openai:** act on the split review of the whole PR ([b3f1910](https://github.com/troupe-run/troupe/commit/b3f191015083b66515900bed2018bbdaa15e3428))
* **runner-openai:** end a refusal's service message as a sentence ([a329597](https://github.com/troupe-run/troupe/commit/a32959712b8cee9deeb222b60358018bac878418))
* **runner-openai:** end the run on a response in the wrong shape ([971654b](https://github.com/troupe-run/troupe/commit/971654b82b1a258a3aedd651abb7b1e10aeaf24e))
* **runner-openai:** report cache reads only when every response does ([f86b79e](https://github.com/troupe-run/troupe/commit/f86b79e51b86e27e3f47641203be03ff8efc8bf3))
* **runner-protocol:** act on the slice reviews of record kinds ([87d51d8](https://github.com/troupe-run/troupe/commit/87d51d83149f7547852f81721a84a2e9d627daef)), closes [#294](https://github.com/troupe-run/troupe/issues/294)
* **runners:** clean a tool call's id and OpenAI's non-stream body ([45ab433](https://github.com/troupe-run/troupe/commit/45ab433c4f9fd08ee3c0b2d8c21c5e4dd229381f))
* **runners:** read OpenAI's and Anthropic's error bodies as text ([d08fb59](https://github.com/troupe-run/troupe/commit/d08fb592feceb0e07dbd57c4b02f92493584055f))
* **runners:** record each lone surrogate replaced, in a context event ([ae9f7a6](https://github.com/troupe-run/troupe/commit/ae9f7a6f3abe27c9d7863c1f5c56a38b23a64cea))
* **runners:** refuse a second initialize with already-initialized ([ad1769b](https://github.com/troupe-run/troupe/commit/ad1769bd880fbb996b1fc94fafcfdd7aad89923e))
* **runners:** write lone surrogates as U+FFFD, never as an escape ([fef4bd5](https://github.com/troupe-run/troupe/commit/fef4bd5c222b1c13014b8e14bf3692d130624d83))
* **runtimes:** count // as a path, as the Ollama runner does ([9be390c](https://github.com/troupe-run/troupe/commit/9be390c3d293df4d64b9a282df9746347a6e6f38))
* **sdk:** never repeat an endpoint refused in run/start ([8619164](https://github.com/troupe-run/troupe/commit/8619164f89eaccaa594c0e9ada5b3eded280ebda))
* **sdk:** refuse a credential a request header can't carry ([b691e3f](https://github.com/troupe-run/troupe/commit/b691e3fe59177461d02de09fed6fff85329b81d9))
