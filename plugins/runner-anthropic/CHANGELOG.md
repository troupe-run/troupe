# Changelog

## [0.2.0](https://github.com/troupe-run/troupe/compare/troupe-runner-anthropic-v0.1.0...troupe-runner-anthropic-v0.2.0) (2026-11-24)


### Features

* **check:** fail a unit test that reaches outside its process ([1847c05](https://github.com/troupe-run/troupe/commit/1847c054abbd0ad917c9f7621114bea2eff886e4)), closes [#507](https://github.com/troupe-run/troupe/issues/507)


### Bug Fixes

* **runner-anthropic:** count and guard by the runtime's engine ([d6cb1b9](https://github.com/troupe-run/troupe/commit/d6cb1b9532cbbf3bca3bd556dfffda9dc280dca9))

## 0.1.0 (2026-11-19)


### ⚠ BREAKING CHANGES

* **sdk:** EventNumbering requires send_context.

### Features

* **runner-anthropic:** add a runner for the Anthropic Messages API ([0d3bd99](https://github.com/troupe-run/troupe/commit/0d3bd995def2ce4d24be238614864170fb109465))
* **runners:** end every runner through the SDK's exit_now, so coverage can save ([217e083](https://github.com/troupe-run/troupe/commit/217e083b5bc9d36dea3b2ccc84277e9e20889b9a)), closes [#443](https://github.com/troupe-run/troupe/issues/443)
* **runtimes:** add an in-process runtime with no endpoint ([3e9ecbd](https://github.com/troupe-run/troupe/commit/3e9ecbdd7e34458cccb6b620b02ae68f87bf6411))
* **sdk:** require send_context to build an EventNumbering ([f172a1a](https://github.com/troupe-run/troupe/commit/f172a1a560b491fa4b5a974dcfb46b30f387c6e5))


### Bug Fixes

* **anthropic:** read a streamed tool input's JSON as Unicode text ([1686d63](https://github.com/troupe-run/troupe/commit/1686d635d5d04616b8781281a1d850368b289051))
* **claude-code:** note a replaced surrogate in the effects server ([96bc001](https://github.com/troupe-run/troupe/commit/96bc00102f8478f4d7c0b528bf46716ff58e912b))
* **runner-anthropic:** answer the handshake before importing the library ([16574e8](https://github.com/troupe-run/troupe/commit/16574e8c755cb4ad8e5b1ade99c8d3ff3b9724b3))
* **runners:** read OpenAI's and Anthropic's error bodies as text ([d08fb59](https://github.com/troupe-run/troupe/commit/d08fb592feceb0e07dbd57c4b02f92493584055f))
* **runners:** record each lone surrogate replaced, in a context event ([ae9f7a6](https://github.com/troupe-run/troupe/commit/ae9f7a6f3abe27c9d7863c1f5c56a38b23a64cea))
* **runners:** refuse a second initialize with already-initialized ([ad1769b](https://github.com/troupe-run/troupe/commit/ad1769bd880fbb996b1fc94fafcfdd7aad89923e))
* **runners:** write lone surrogates as U+FFFD, never as an escape ([fef4bd5](https://github.com/troupe-run/troupe/commit/fef4bd5c222b1c13014b8e14bf3692d130624d83))
