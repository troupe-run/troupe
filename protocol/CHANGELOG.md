# Changelog

## 0.1.0 (2026-10-24)


### ⚠ BREAKING CHANGES

* **events:** segments written before this change have no "protocol" in their header and are refused as malformed records.
* **perform:** troupe perform's --runner, --runner-options, --expect and --no-effect-check are removed, with no overrides, and --instructions is now --direction. perform --rehearse shows what would run and exits 3. Run.Started's payload drops instructions and options.
* **runs:** segments, run events and client messages no longer carry nulls, and readers refuse them; there are no theatres to migrate.
* **lineage:** lineage written before this omits nothing and won't validate; there are no theatres to migrate.
* **cli:** usage.invalid and usage.unknown-flag details now carry the command (null before one is chosen). Nothing outside this repo reads them.
* **runners:** the runner contract is version 0, the draft
* **protocol:** error and notice detail keys that were snake_case are now camelCase (exitCode, limitBytes, waitedSeconds and the rest), and events.unknown-format's format detail is JSON text. Nothing outside this repository reads them.
* **runner-protocol:** a run event carrying native is a protocol violation. Only this repository's scripted runner and fixtures used it.

### Features

* **cli:** a structured code for each usage shape, naming the command ([c0161a5](https://github.com/troupe-run/troupe/commit/c0161a5246f98ce535723b34007bc27615fd2032)), closes [#53](https://github.com/troupe-run/troupe/issues/53)
* **client:** define perform, status and logs as client protocol messages, and one dispatcher ([3063cb5](https://github.com/troupe-run/troupe/commit/3063cb52e50ea9fdfb7d1435263c4419b1fcc2ae))
* **cli:** troupe config set, unset and get, and troupe flush ([#60](https://github.com/troupe-run/troupe/issues/60)) ([5741671](https://github.com/troupe-run/troupe/commit/5741671364541c3b4825f7ab668162786d540904))
* **config:** an actor's workspace, worktree by default or theatre to run in place ([#51](https://github.com/troupe-run/troupe/issues/51)) ([fdf718c](https://github.com/troupe-run/troupe/commit/fdf718c26e3ffab8cec6571ebd81f11691b6dcba))
* **config:** build a command's change from its values, and check config before recording it ([#60](https://github.com/troupe-run/troupe/issues/60)) ([b53ce3a](https://github.com/troupe-run/troupe/commit/b53ce3a800a0e48892b4c147012d08428a46c39a))
* **config:** project config to files under .troupe/, replacing only the files troupe wrote ([#60](https://github.com/troupe-run/troupe/issues/60)) ([e2ac5c1](https://github.com/troupe-run/troupe/commit/e2ac5c1693bcac370fa7e5d0c6560f70456f5fa2))
* **config:** rewrite a config file git merged from troupe's versions ([#141](https://github.com/troupe-run/troupe/issues/141)) ([a16b65e](https://github.com/troupe-run/troupe/commit/a16b65e9fe772db63e4f3b7bbbbdade823840fc7))
* **config:** the actor and Config.Changed schemas, with pydantic models generated from them ([#60](https://github.com/troupe-run/troupe/issues/60)) ([a33468d](https://github.com/troupe-run/troupe/commit/a33468d6074c46ddf173c601b7b282922cbd6c35))
* **config:** work out config across branches by each line's net change, and settle with the next write ([#60](https://github.com/troupe-run/troupe/issues/60)) ([c207cb2](https://github.com/troupe-run/troupe/commit/c207cb2de1bf52cd868876d9eaefd29b863bff82))
* **core:** derive run outcomes, check effects, and read JSON strictly ([610b5b5](https://github.com/troupe-run/troupe/commit/610b5b51ffeb0c544e9eb4c9040904e05bd04088))
* **docs:** generate the CLI, exit-code, event and config reference from their sources ([5870168](https://github.com/troupe-run/troupe/commit/587016883052236b5a99514a1fcee265e373b2b5)), closes [#123](https://github.com/troupe-run/troupe/issues/123)
* **event-store:** give each event troupe records a payload schema by topic ([12b1275](https://github.com/troupe-run/troupe/commit/12b1275fc20b17daec38c204c9b874abb6760039))
* **events:** name the protocol that wrote a segment in its header, and report it in --version ([#140](https://github.com/troupe-run/troupe/issues/140)) ([ddf0c0b](https://github.com/troupe-run/troupe/commit/ddf0c0bba65fe5ba80e5a1bdac1c30d83b1a6af9))
* **events:** record the stage and whether effects were enforced in lineage ([0bbcdde](https://github.com/troupe-run/troupe/commit/0bbcdde064afa6e354714a556ece5b6fb30994c0))
* **lineage:** leave absent lineage fields out instead of null ([0f3e59c](https://github.com/troupe-run/troupe/commit/0f3e59c42b413a49c6beadec6459c8c46efd60e5)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
* **perform:** take the actor's runner, options, effect check and character from config ([#60](https://github.com/troupe-run/troupe/issues/60)) ([514c788](https://github.com/troupe-run/troupe/commit/514c78811cf42f00e491403c114e56139ce685eb))
* **protocol:** catalogue every error and notice code with closed details ([36f8241](https://github.com/troupe-run/troupe/commit/36f824164ede66cba5128ab7f79c2fb25a7af7c0))
* **protocol:** define lineage and event records as JSON Schema ([04efe9c](https://github.com/troupe-run/troupe/commit/04efe9c72ff5258a27264e5230ebd76cb6833494))
* **protocol:** define the runner contract as JSON Schema ([f3b8043](https://github.com/troupe-run/troupe/commit/f3b8043ae911bdebfe05d6c6f66e88f1054bb6cc))
* **protocol:** mark the JSON-RPC error id as the one null ([5244b9a](https://github.com/troupe-run/troupe/commit/5244b9afdf440bd42c48f8841513b90715b0636b)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
* **protocol:** read the protocol version troupe carries from its one record ([#140](https://github.com/troupe-run/troupe/issues/140)) ([f7a86cd](https://github.com/troupe-run/troupe/commit/f7a86cd5b5e86677b2ab7af7fc7ad0708712028f))
* **protocol:** require UUID run ids and negotiate capabilities ([b254355](https://github.com/troupe-run/troupe/commit/b2543554254dbc2393891aee10713ac8cc4a73c9))
* **runner-protocol:** close run events, results and runner errors ([613ca5b](https://github.com/troupe-run/troupe/commit/613ca5bfc2f7af4519adb47f98d9a50c6826e0db))
* **runner-protocol:** runner options are an extension point the runner fills ([84b46c3](https://github.com/troupe-run/troupe/commit/84b46c3e251cfcf29e1702fc77bcb00e02760d04))
* **runner:** run/start carries the run's direction and the actor's character ([#60](https://github.com/troupe-run/troupe/issues/60)) ([7eece31](https://github.com/troupe-run/troupe/commit/7eece31b55367f2ec6b7a2b022b2aeffed361500))
* **runners:** the runner contract is version 0, the draft ([69d6c27](https://github.com/troupe-run/troupe/commit/69d6c276db144bd47bdfb39e69d2ac3e03bc6144))
* **runs:** perform in a worktree by default, and diff, accept or discard its changes ([#51](https://github.com/troupe-run/troupe/issues/51)) ([564f0cc](https://github.com/troupe-run/troupe/commit/564f0cc31f630c7ddb1a7a7d8bdca9a575a0b6c0))
* **runs:** record a run's workspace and captured changes, and accepting or discarding them ([#51](https://github.com/troupe-run/troupe/issues/51)) ([264cb92](https://github.com/troupe-run/troupe/commit/264cb927244ac8991f42ac6aaaec4bd5a43496ce))
* **runs:** record and report runs without nulls ([9cc2f37](https://github.com/troupe-run/troupe/commit/9cc2f37cfc11cbf19c5c96504278def720a7e030)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
* **schemas:** troupe carries the protocol's schemas, and reads a runner's from the installed runner ([#60](https://github.com/troupe-run/troupe/issues/60)) ([5ea49b2](https://github.com/troupe-run/troupe/commit/5ea49b24d218e5c0c7ebbb849dbab45a6f7950d0))
* **vcs:** make, fill, diff, apply and remove a run's worktree, and snapshot shared git state ([#51](https://github.com/troupe-run/troupe/issues/51)) ([6ba3ac5](https://github.com/troupe-run/troupe/commit/6ba3ac5c3381014ba7abe5c2b5ee1b77729885cc))


### Bug Fixes

* **cli:** leave a usage error's command out before any command ([1471634](https://github.com/troupe-run/troupe/commit/1471634ed624aa21233835eb3cffb879288258db)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
* **cli:** take dash-leading text with a space as an option's value ([b045773](https://github.com/troupe-run/troupe/commit/b045773b89f10ca102083847dd6f8fb34c7a6896)), closes [#53](https://github.com/troupe-run/troupe/issues/53)
* **event-store:** stopping a subscription waits for its thread, bounded ([1ecd201](https://github.com/troupe-run/troupe/commit/1ecd201eca7ed8d60ae8e7a1a5a51a09e793201e))
* **protocol:** catalogue events.subscription-polling from [#74](https://github.com/troupe-run/troupe/issues/74) ([6da20b8](https://github.com/troupe-run/troupe/commit/6da20b81ba4fb27663fe72b0941f49b0279803c6))
* **vcs:** don't refuse a theatre whose commit holds a file git would normalise ([#51](https://github.com/troupe-run/troupe/issues/51)) ([526682b](https://github.com/troupe-run/troupe/commit/526682b9e0d9425960d795a0ac8dc45d6f8d1caa))
