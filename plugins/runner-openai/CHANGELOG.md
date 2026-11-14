# Changelog

## 0.1.0 (2026-11-14)


### ⚠ BREAKING CHANGES

* **runner-protocol:** a runner that predates this rejects run/start's new onContextFull field. The contract is version 0, and every runner is in this repository.
* **runner-protocol:** a runner's result with status error must carry a reason from the contract's list, and an ok result must not; troupe refuses either as a protocol violation, and run.error-result's details now require the reason. Every runner that speaks the contract is in this repository and is updated here; there are no recorded theatres to migrate.
* **runner-protocol:** a Run.Ended outcome with a transcript but no transcriptFormat no longer validates, so ends recorded before this change don't read back (pre-1.0: there are no theatres in use). the OpenAI runner's transcript records are the bytes themselves with the contract's kinds, not its own JSON objects with kind request, response, stream, body or dropped, and the request URL is no longer recorded.

### Features

* **config:** refuse an actor whose runner can't use its runtime ([ed15536](https://github.com/troupe-run/troupe/commit/ed1553634db7689202f6bd9bda6467aba1c89a5f))
* **openai:** a run told to compact stubs old outputs after a refusal ([43a2891](https://github.com/troupe-run/troupe/commit/43a28914cff30c7952889317356d09d851cb0047))
* **plugin-sdk:** define what a credential's value may hold, once ([d97ce8f](https://github.com/troupe-run/troupe/commit/d97ce8f109d062215c690f93a8cffbf3e1b82516))
* **runner-openai:** estimate a run's cost from troupe's price ([5307f14](https://github.com/troupe-run/troupe/commit/5307f147e9aeb7e994ad8b7a655408c376edf9f1))
* **runner-openai:** rename to openai, ship it, and give it an audition ([f4cedac](https://github.com/troupe-run/troupe/commit/f4cedac9f3ce3e90af0b397c62a4910be6f3b997))
* **runner-openai:** speak the Responses API ([321699d](https://github.com/troupe-run/troupe/commit/321699d2f67e2cc2c51f530b9bd1a1406521661d))
* **runner-protocol:** a failed result says why, in a reason ([3dcfe3f](https://github.com/troupe-run/troupe/commit/3dcfe3f344d1621109761bedbe5eda5ed773b5a7)), closes [#296](https://github.com/troupe-run/troupe/issues/296)
* **runner-protocol:** report the model that served a run ([409a5f9](https://github.com/troupe-run/troupe/commit/409a5f9c82361e8134d88816010d98e47419defc)), closes [#295](https://github.com/troupe-run/troupe/issues/295)
* **runner-protocol:** run/start says whether the run may compact ([21851c3](https://github.com/troupe-run/troupe/commit/21851c36e6b9e74a5cf7715325580119fe6b8cf1))
* **runner-protocol:** transcript records can say what kind they are ([a0c3fd4](https://github.com/troupe-run/troupe/commit/a0c3fd4d6b13778e4c47833e2cf2c4f062ada922))
* **runtimes:** add an in-process runtime with no endpoint ([3e9ecbd](https://github.com/troupe-run/troupe/commit/3e9ecbdd7e34458cccb6b620b02ae68f87bf6411))
* **runtimes:** refuse a credential holding whitespace in core ([cac94eb](https://github.com/troupe-run/troupe/commit/cac94ebbed4a886a4aaf4119b16c5e9f9a015df9))


### Bug Fixes

* **openai:** keep requests below an endpoint whose path is // ([1f85a18](https://github.com/troupe-run/troupe/commit/1f85a18fb7ed4d4ea54bd0081d9067581bcf98da))
* **runner-openai:** act on an independent review of unread files ([a00c1aa](https://github.com/troupe-run/troupe/commit/a00c1aa509c357ac3a662e92b3cd61a4f181ef22))
* **runner-openai:** act on the split review of the whole PR ([b3f1910](https://github.com/troupe-run/troupe/commit/b3f191015083b66515900bed2018bbdaa15e3428))
* **runner-openai:** end a refusal's service message as a sentence ([a329597](https://github.com/troupe-run/troupe/commit/a32959712b8cee9deeb222b60358018bac878418))
* **runner-openai:** end the run on a response in the wrong shape ([971654b](https://github.com/troupe-run/troupe/commit/971654b82b1a258a3aedd651abb7b1e10aeaf24e))
* **runner-openai:** report cache reads only when every response does ([f86b79e](https://github.com/troupe-run/troupe/commit/f86b79e51b86e27e3f47641203be03ff8efc8bf3))
* **runner-protocol:** act on the slice reviews of record kinds ([87d51d8](https://github.com/troupe-run/troupe/commit/87d51d83149f7547852f81721a84a2e9d627daef)), closes [#294](https://github.com/troupe-run/troupe/issues/294)
* **runtimes:** count // as a path, as the Ollama runner does ([9be390c](https://github.com/troupe-run/troupe/commit/9be390c3d293df4d64b9a282df9746347a6e6f38))
* **sdk:** never repeat an endpoint refused in run/start ([8619164](https://github.com/troupe-run/troupe/commit/8619164f89eaccaa594c0e9ada5b3eded280ebda))
* **sdk:** refuse a credential a request header can't carry ([b691e3f](https://github.com/troupe-run/troupe/commit/b691e3fe59177461d02de09fed6fff85329b81d9))
