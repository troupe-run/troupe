# Changelog

## 0.1.0 (2026-10-17)


### ⚠ BREAKING CHANGES

* **runs:** segments, run events and client messages no longer carry nulls, and readers refuse them; there are no theatres to migrate.
* **lineage:** lineage written before this omits nothing and won't validate; there are no theatres to migrate.
* **cli:** usage.invalid and usage.unknown-flag details now carry the command (null before one is chosen). Nothing outside this repo reads them.
* **runners:** the runner contract is version 0, the draft
* **protocol:** error and notice detail keys that were snake_case are now camelCase (exitCode, limitBytes, waitedSeconds and the rest), and events.unknown-format's format detail is JSON text. Nothing outside this repository reads them.
* **runner-protocol:** a run event carrying native is a protocol violation. Only this repository's scripted runner and fixtures used it.

### Features

* **cli:** a structured code for each usage shape, naming the command ([c0161a5](https://github.com/troupe-run/troupe/commit/c0161a5246f98ce535723b34007bc27615fd2032)), closes [#53](https://github.com/troupe-run/troupe/issues/53)
* **client:** define perform, status and logs as client protocol messages, and one dispatcher ([3063cb5](https://github.com/troupe-run/troupe/commit/3063cb52e50ea9fdfb7d1435263c4419b1fcc2ae))
* **core:** derive run outcomes, check effects, and read JSON strictly ([610b5b5](https://github.com/troupe-run/troupe/commit/610b5b51ffeb0c544e9eb4c9040904e05bd04088))
* **event-store:** give each event troupe records a payload schema by topic ([12b1275](https://github.com/troupe-run/troupe/commit/12b1275fc20b17daec38c204c9b874abb6760039))
* **events:** record the stage and whether effects were enforced in lineage ([0bbcdde](https://github.com/troupe-run/troupe/commit/0bbcdde064afa6e354714a556ece5b6fb30994c0))
* **lineage:** leave absent lineage fields out instead of null ([0f3e59c](https://github.com/troupe-run/troupe/commit/0f3e59c42b413a49c6beadec6459c8c46efd60e5)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
* **protocol:** catalogue every error and notice code with closed details ([36f8241](https://github.com/troupe-run/troupe/commit/36f824164ede66cba5128ab7f79c2fb25a7af7c0))
* **protocol:** define lineage and event records as JSON Schema ([04efe9c](https://github.com/troupe-run/troupe/commit/04efe9c72ff5258a27264e5230ebd76cb6833494))
* **protocol:** define the runner contract as JSON Schema ([f3b8043](https://github.com/troupe-run/troupe/commit/f3b8043ae911bdebfe05d6c6f66e88f1054bb6cc))
* **protocol:** mark the JSON-RPC error id as the one null ([5244b9a](https://github.com/troupe-run/troupe/commit/5244b9afdf440bd42c48f8841513b90715b0636b)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
* **protocol:** require UUID run ids and negotiate capabilities ([b254355](https://github.com/troupe-run/troupe/commit/b2543554254dbc2393891aee10713ac8cc4a73c9))
* **runner-protocol:** close run events, results and runner errors ([613ca5b](https://github.com/troupe-run/troupe/commit/613ca5bfc2f7af4519adb47f98d9a50c6826e0db))
* **runner-protocol:** runner options are an extension point the runner fills ([84b46c3](https://github.com/troupe-run/troupe/commit/84b46c3e251cfcf29e1702fc77bcb00e02760d04))
* **runners:** the runner contract is version 0, the draft ([69d6c27](https://github.com/troupe-run/troupe/commit/69d6c276db144bd47bdfb39e69d2ac3e03bc6144))
* **runs:** record and report runs without nulls ([9cc2f37](https://github.com/troupe-run/troupe/commit/9cc2f37cfc11cbf19c5c96504278def720a7e030)), closes [#76](https://github.com/troupe-run/troupe/issues/76)


### Bug Fixes

* **cli:** leave a usage error's command out before any command ([1471634](https://github.com/troupe-run/troupe/commit/1471634ed624aa21233835eb3cffb879288258db)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
* **cli:** take dash-leading text with a space as an option's value ([b045773](https://github.com/troupe-run/troupe/commit/b045773b89f10ca102083847dd6f8fb34c7a6896)), closes [#53](https://github.com/troupe-run/troupe/issues/53)
* **event-store:** stopping a subscription waits for its thread, bounded ([1ecd201](https://github.com/troupe-run/troupe/commit/1ecd201eca7ed8d60ae8e7a1a5a51a09e793201e))
* **protocol:** catalogue events.subscription-polling from [#74](https://github.com/troupe-run/troupe/issues/74) ([6da20b8](https://github.com/troupe-run/troupe/commit/6da20b81ba4fb27663fe72b0941f49b0279803c6))
