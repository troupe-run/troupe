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
* **cli:** add --version, flags anywhere, the -- rule and structured errors ([74cbf20](https://github.com/troupe-run/troupe/commit/74cbf20e801c087bd17e9e0d5038a6a34e182190))
* **cli:** add troupe perform, status and logs ([b691f98](https://github.com/troupe-run/troupe/commit/b691f984dcc39d632293f5c768dbc5c7a2ec36ff))
* **client:** define perform, status and logs as client protocol messages, and one dispatcher ([3063cb5](https://github.com/troupe-run/troupe/commit/3063cb52e50ea9fdfb7d1435263c4419b1fcc2ae))
* **core:** add a conformance suite any runner can be checked against ([2022a60](https://github.com/troupe-run/troupe/commit/2022a60b9183f244322885c42beefbf07cf0debf))
* **core:** add a content-addressed artifact store ([3ff0ff4](https://github.com/troupe-run/troupe/commit/3ff0ff4bcf8233f1243f2017734ad2f1486f6c3a))
* **core:** add runner limits, error codes and protocol types ([a63228d](https://github.com/troupe-run/troupe/commit/a63228d4549b2d5f9d1aaf7cb682fec4c1d6976c))
* **core:** derive run outcomes, check effects, and read JSON strictly ([610b5b5](https://github.com/troupe-run/troupe/commit/610b5b51ffeb0c544e9eb4c9040904e05bd04088))
* **core:** find the theatre from the working directory, and name runners from an interim table ([5974bc8](https://github.com/troupe-run/troupe/commit/5974bc89f72956288af5c745b919636165af947e))
* **core:** read policy through one seam, with an interim environment source ([1eeed3f](https://github.com/troupe-run/troupe/commit/1eeed3f04e3dc5c3f4e994d64a3e4620f3f4e397))
* **core:** run actors through a supervised runner ([0cfea69](https://github.com/troupe-run/troupe/commit/0cfea69e940d09e5246ca1b705334b1a35d7d607))
* **event-store:** give each event troupe records a payload schema by topic ([12b1275](https://github.com/troupe-run/troupe/commit/12b1275fc20b17daec38c204c9b874abb6760039))
* **events:** detect forked streams and settle them with an event that names every head ([b33eb25](https://github.com/troupe-run/troupe/commit/b33eb25f5e426e62cc87fc77f5be3fae0df61dc9))
* **events:** record every event with lineage, correlation and cause ([3bcfe5c](https://github.com/troupe-run/troupe/commit/3bcfe5c2d7b0f7eef8d5b984c609892254868e11))
* **events:** record the stage and whether effects were enforced in lineage ([0bbcdde](https://github.com/troupe-run/troupe/commit/0bbcdde064afa6e354714a556ece5b6fb30994c0))
* **events:** subscriptions deliver other writers' events as they're recorded ([f8f9416](https://github.com/troupe-run/troupe/commit/f8f9416b65cb0ccb19a39689572921a00d5f6b68))
* **identity:** resolve who is acting through an ordered chain of sources ([c6ab0fb](https://github.com/troupe-run/troupe/commit/c6ab0fbc358309316a522e3e4bddbac6cb8722f3))
* **lineage:** leave absent lineage fields out instead of null ([0f3e59c](https://github.com/troupe-run/troupe/commit/0f3e59c42b413a49c6beadec6459c8c46efd60e5)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
* **platform:** add atomic replace, lock-file locks and friendly paths ([8d48325](https://github.com/troupe-run/troupe/commit/8d48325bf3cf2bf8698d35f908be92bbef3572cf))
* **platform:** build child environments from declared policies ([ceb444f](https://github.com/troupe-run/troupe/commit/ceb444fbcf1abd7a10ed4572f32f0bcd91a8bea9))
* **platform:** catch Ctrl-C through one hook on every OS ([8edaa79](https://github.com/troupe-run/troupe/commit/8edaa79804e40c01b1171f25e6b56b59cde8d634))
* **platform:** decide whether a process has ended from one table per platform ([6a91e57](https://github.com/troupe-run/troupe/commit/6a91e571d722bd09daf8ef4a20897f229d744169))
* **platform:** run a short command to completion within a bound ([a9c00da](https://github.com/troupe-run/troupe/commit/a9c00da093a27fc4e1f93afe71646b34f58085ba))
* **platform:** say whether troupe's kill is what ended a child ([141da77](https://github.com/troupe-run/troupe/commit/141da77a0b9cf42dc6bce656d035970402ffe02e)), closes [#86](https://github.com/troupe-run/troupe/issues/86)
* **platform:** start and kill child processes on all three platforms ([18b988b](https://github.com/troupe-run/troupe/commit/18b988ba7258c1171d1b2480a46557719c1c38ba))
* **platform:** watch a directory for changes on Linux, macOS and Windows ([1d857fe](https://github.com/troupe-run/troupe/commit/1d857fe1940536eb3d2271d961253ab143fbc669))
* **protocol:** catalogue every error and notice code with closed details ([36f8241](https://github.com/troupe-run/troupe/commit/36f824164ede66cba5128ab7f79c2fb25a7af7c0))
* **protocol:** define lineage and event records as JSON Schema ([04efe9c](https://github.com/troupe-run/troupe/commit/04efe9c72ff5258a27264e5230ebd76cb6833494))
* **protocol:** define the runner contract as JSON Schema ([f3b8043](https://github.com/troupe-run/troupe/commit/f3b8043ae911bdebfe05d6c6f66e88f1054bb6cc))
* **protocol:** mark the JSON-RPC error id as the one null ([5244b9a](https://github.com/troupe-run/troupe/commit/5244b9afdf440bd42c48f8841513b90715b0636b)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
* **protocol:** require UUID run ids and negotiate capabilities ([b254355](https://github.com/troupe-run/troupe/commit/b2543554254dbc2393891aee10713ac8cc4a73c9))
* **runner-protocol:** close run events, results and runner errors ([613ca5b](https://github.com/troupe-run/troupe/commit/613ca5bfc2f7af4519adb47f98d9a50c6826e0db))
* **runner-protocol:** runner options are an extension point the runner fills ([84b46c3](https://github.com/troupe-run/troupe/commit/84b46c3e251cfcf29e1702fc77bcb00e02760d04))
* **runners:** the runner contract is version 0, the draft ([69d6c27](https://github.com/troupe-run/troupe/commit/69d6c276db144bd47bdfb39e69d2ac3e03bc6144))
* **runs:** logs --follow subscribes to the store instead of polling ([c7fc057](https://github.com/troupe-run/troupe/commit/c7fc0579e6b41f5a2b4a6e852169a4aa063f3115))
* **runs:** perform runs one actor and records the run in its own stream ([351704d](https://github.com/troupe-run/troupe/commit/351704d70f1f52f1d5e543eaab99d8f7622c205a))
* **runs:** read runs back with status and logs, from projections ([16a6bc6](https://github.com/troupe-run/troupe/commit/16a6bc61620d4aff749567169c30c9e39250d0c1))
* **runs:** record and report runs without nulls ([9cc2f37](https://github.com/troupe-run/troupe/commit/9cc2f37cfc11cbf19c5c96504278def720a7e030)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
* **runs:** show followed events as they're recorded, and test a real Ctrl-C on Windows ([b751e1b](https://github.com/troupe-run/troupe/commit/b751e1ba951fceac2fb4b3575c9ba8c8e0ea26eb))
* **scripts:** declare which paths need which part of the check ([e9f7db5](https://github.com/troupe-run/troupe/commit/e9f7db51ac9395253c9752815a8d85621431e7e8))
* **stages:** add the stage port and a local stage that refuses unless policy allows it ([9908c0c](https://github.com/troupe-run/troupe/commit/9908c0c15ba6170edd623ba519c1469b4108558f))
* **store:** encode and read segment lines with content-hash ids ([955f753](https://github.com/troupe-run/troupe/commit/955f7539a169081c7cbbe127ed673a1ce2d0445a))
* **store:** record events in per-session segments with a local order ([1c82430](https://github.com/troupe-run/troupe/commit/1c82430b82cdd85d70801db2f24a1bb3a1399c58))
* **vcs:** read branch, HEAD and what is committed through a VCS port ([4729252](https://github.com/troupe-run/troupe/commit/4729252008441c7fe66abb20330ca8e9f8f1e686))
* **workspace:** add the event-store adapter packages and their import contracts ([6746785](https://github.com/troupe-run/troupe/commit/67467850696f4da6df5330c47e78133cdae4a38f))


### Bug Fixes

* **cli:** a trailing `--` with nothing after it changes nothing ([fe9a0d9](https://github.com/troupe-run/troupe/commit/fe9a0d97448e6767291ae4d9dd4f86c34c8e8d09))
* **cli:** leave a usage error's command out before any command ([1471634](https://github.com/troupe-run/troupe/commit/1471634ed624aa21233835eb3cffb879288258db)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
* **cli:** print the troupe: prefix once on argparse's usage errors ([f0a639a](https://github.com/troupe-run/troupe/commit/f0a639ab918940f15824559d947d6df96520bdbf)), closes [#53](https://github.com/troupe-run/troupe/issues/53)
* **cli:** take dash-leading text with a space as an option's value ([b045773](https://github.com/troupe-run/troupe/commit/b045773b89f10ca102083847dd6f8fb34c7a6896)), closes [#53](https://github.com/troupe-run/troupe/issues/53)
* **event-store:** stopping a subscription waits for its thread, bounded ([1ecd201](https://github.com/troupe-run/troupe/commit/1ecd201eca7ed8d60ae8e7a1a5a51a09e793201e))
* **events:** pad lineage years to four digits on every platform ([3fb1694](https://github.com/troupe-run/troupe/commit/3fb1694762b044687ca6d6df295266ef1063e592))
* **platform:** a wait that times out has always been announced ([d7c6232](https://github.com/troupe-run/troupe/commit/d7c62322fa5ce3863566175e0ba608dad4a463b8))
* **platform:** a watch wait returns no earlier than its timeout, on every platform ([37c23ff](https://github.com/troupe-run/troupe/commit/37c23ff61df516be9d14372cabeb8cefd55d57d8))
* **platform:** a watched directory removed on Windows is missing, not unwatchable ([a76a4b5](https://github.com/troupe-run/troupe/commit/a76a4b5b87f779857c6d3b60362691e03602260d))
* **platform:** describe Windows error codes of 2**31 and above ([5cb7ad0](https://github.com/troupe-run/troupe/commit/5cb7ad0871734dc9e934144e6aa040c1a7816365))
* **platform:** is_running says whether a process has ended, on every platform ([7ec3d6a](https://github.com/troupe-run/troupe/commit/7ec3d6ab6ba4683313a26808cd536a0c862295b1)), closes [#92](https://github.com/troupe-run/troupe/issues/92)
* **platform:** retry Windows' brief refusal to read a file mid-replace ([debf713](https://github.com/troupe-run/troupe/commit/debf713285b52332e1a68c23f31eccba5b44964e))
* **platform:** the interrupt test's child counts in its handler, not prints ([b86950b](https://github.com/troupe-run/troupe/commit/b86950bccc1f3cc1a8945bba6289b95b06c5109e))
* **runners:** record a run as killed only when troupe's kill ended it ([749212a](https://github.com/troupe-run/troupe/commit/749212a9fb3de3c654dfed83389bf9253d91d682)), closes [#86](https://github.com/troupe-run/troupe/issues/86)
* **runners:** take a run's exit code from the wait that ended it ([319eb40](https://github.com/troupe-run/troupe/commit/319eb40171eb3250fca5146b6e070d9463f4596a)), closes [#76](https://github.com/troupe-run/troupe/issues/76)


### Documentation

* **events:** describe the event store, and measure a cold read of 10,000 segments ([a7bd68b](https://github.com/troupe-run/troupe/commit/a7bd68b3820709769f77ffef84deb549f6e28d93))
* **openspec:** archive perform-status-logs and sync its specs ([a527b43](https://github.com/troupe-run/troupe/commit/a527b43e3b0b55221627d47c816da6e9c06c0662))
