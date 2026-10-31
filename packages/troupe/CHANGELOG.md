# Changelog

## 0.1.0 (2026-10-31)


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

* **cli:** --rehearse on config set, config unset and flush, exiting 3 when it would change something ([#60](https://github.com/troupe-run/troupe/issues/60)) ([c726dce](https://github.com/troupe-run/troupe/commit/c726dce67bdb4a0b49f68ba6414f3e68e77627cf))
* **cli:** a structured code for each usage shape, naming the command ([c0161a5](https://github.com/troupe-run/troupe/commit/c0161a5246f98ce535723b34007bc27615fd2032)), closes [#53](https://github.com/troupe-run/troupe/issues/53)
* **cli:** add troupe perform, status and logs ([b691f98](https://github.com/troupe-run/troupe/commit/b691f984dcc39d632293f5c768dbc5c7a2ec36ff))
* **client:** define perform, status and logs as client protocol messages, and one dispatcher ([3063cb5](https://github.com/troupe-run/troupe/commit/3063cb52e50ea9fdfb7d1435263c4419b1fcc2ae))
* **cli:** troupe config set, unset and get, and troupe flush ([#60](https://github.com/troupe-run/troupe/issues/60)) ([5741671](https://github.com/troupe-run/troupe/commit/5741671364541c3b4825f7ab668162786d540904))
* **config:** an actor's workspace, worktree by default or theatre to run in place ([#51](https://github.com/troupe-run/troupe/issues/51)) ([fdf718c](https://github.com/troupe-run/troupe/commit/fdf718c26e3ffab8cec6571ebd81f11691b6dcba))
* **config:** build a command's change from its values, and check config before recording it ([#60](https://github.com/troupe-run/troupe/issues/60)) ([b53ce3a](https://github.com/troupe-run/troupe/commit/b53ce3a800a0e48892b4c147012d08428a46c39a))
* **config:** mark a rewritten conflicted config file resolved ([2684390](https://github.com/troupe-run/troupe/commit/2684390f1dc17ee9c54abe869ed9a98f4877e41a))
* **config:** project config to files under .troupe/, replacing only the files troupe wrote ([#60](https://github.com/troupe-run/troupe/issues/60)) ([e2ac5c1](https://github.com/troupe-run/troupe/commit/e2ac5c1693bcac370fa7e5d0c6560f70456f5fa2))
* **config:** rewrite a config file git merged from troupe's versions ([#141](https://github.com/troupe-run/troupe/issues/141)) ([a16b65e](https://github.com/troupe-run/troupe/commit/a16b65e9fe772db63e4f3b7bbbbdade823840fc7))
* **config:** the actor and Config.Changed schemas, with pydantic models generated from them ([#60](https://github.com/troupe-run/troupe/issues/60)) ([a33468d](https://github.com/troupe-run/troupe/commit/a33468d6074c46ddf173c601b7b282922cbd6c35))
* **config:** work out config across branches by each line's net change, and settle with the next write ([#60](https://github.com/troupe-run/troupe/issues/60)) ([c207cb2](https://github.com/troupe-run/troupe/commit/c207cb2de1bf52cd868876d9eaefd29b863bff82))
* **core:** find the theatre from the working directory, and name runners from an interim table ([5974bc8](https://github.com/troupe-run/troupe/commit/5974bc89f72956288af5c745b919636165af947e))
* **core:** read policy through one seam, with an interim environment source ([1eeed3f](https://github.com/troupe-run/troupe/commit/1eeed3f04e3dc5c3f4e994d64a3e4620f3f4e397))
* **docs:** generate the CLI, exit-code, event and config reference from their sources ([5870168](https://github.com/troupe-run/troupe/commit/587016883052236b5a99514a1fcee265e373b2b5)), closes [#123](https://github.com/troupe-run/troupe/issues/123)
* **event-store:** give each event troupe records a payload schema by topic ([12b1275](https://github.com/troupe-run/troupe/commit/12b1275fc20b17daec38c204c9b874abb6760039))
* **events:** detect forked streams and settle them with an event that names every head ([b33eb25](https://github.com/troupe-run/troupe/commit/b33eb25f5e426e62cc87fc77f5be3fae0df61dc9))
* **events:** let an aggregate read a forked stream whole and settle it with its next change ([#60](https://github.com/troupe-run/troupe/issues/60)) ([6a5696f](https://github.com/troupe-run/troupe/commit/6a5696f17a6f607c0f9584ecd245686487a59744))
* **events:** name the protocol that wrote a segment in its header, and report it in --version ([#140](https://github.com/troupe-run/troupe/issues/140)) ([ddf0c0b](https://github.com/troupe-run/troupe/commit/ddf0c0bba65fe5ba80e5a1bdac1c30d83b1a6af9))
* **events:** record every event with lineage, correlation and cause ([3bcfe5c](https://github.com/troupe-run/troupe/commit/3bcfe5c2d7b0f7eef8d5b984c609892254868e11))
* **events:** record the stage and whether effects were enforced in lineage ([0bbcdde](https://github.com/troupe-run/troupe/commit/0bbcdde064afa6e354714a556ece5b6fb30994c0))
* **events:** subscriptions deliver other writers' events as they're recorded ([f8f9416](https://github.com/troupe-run/troupe/commit/f8f9416b65cb0ccb19a39689572921a00d5f6b68))
* **identity:** resolve who is acting through an ordered chain of sources ([c6ab0fb](https://github.com/troupe-run/troupe/commit/c6ab0fbc358309316a522e3e4bddbac6cb8722f3))
* **lineage:** leave absent lineage fields out instead of null ([0f3e59c](https://github.com/troupe-run/troupe/commit/0f3e59c42b413a49c6beadec6459c8c46efd60e5)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
* **perform:** take the actor's runner, options, effect check and character from config ([#60](https://github.com/troupe-run/troupe/issues/60)) ([514c788](https://github.com/troupe-run/troupe/commit/514c78811cf42f00e491403c114e56139ce685eb))
* **platform:** catch Ctrl-C through one hook on every OS ([8edaa79](https://github.com/troupe-run/troupe/commit/8edaa79804e40c01b1171f25e6b56b59cde8d634))
* **platform:** clone a file copy-on-write, falling back to a plain copy ([#51](https://github.com/troupe-run/troupe/issues/51)) ([4dc3edf](https://github.com/troupe-run/troupe/commit/4dc3edf6fee28f364541616b5edc6b109d0e076b))
* **platform:** decide whether a process has ended from one table per platform ([6a91e57](https://github.com/troupe-run/troupe/commit/6a91e571d722bd09daf8ef4a20897f229d744169))
* **platform:** say whether troupe's kill is what ended a child ([141da77](https://github.com/troupe-run/troupe/commit/141da77a0b9cf42dc6bce656d035970402ffe02e)), closes [#86](https://github.com/troupe-run/troupe/issues/86)
* **platform:** watch a directory for changes on Linux, macOS and Windows ([1d857fe](https://github.com/troupe-run/troupe/commit/1d857fe1940536eb3d2271d961253ab143fbc669))
* **protocol:** catalogue every error and notice code with closed details ([36f8241](https://github.com/troupe-run/troupe/commit/36f824164ede66cba5128ab7f79c2fb25a7af7c0))
* **protocol:** define lineage and event records as JSON Schema ([04efe9c](https://github.com/troupe-run/troupe/commit/04efe9c72ff5258a27264e5230ebd76cb6833494))
* **protocol:** mark the JSON-RPC error id as the one null ([5244b9a](https://github.com/troupe-run/troupe/commit/5244b9afdf440bd42c48f8841513b90715b0636b)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
* **protocol:** read the protocol version troupe carries from its one record ([#140](https://github.com/troupe-run/troupe/issues/140)) ([f7a86cd](https://github.com/troupe-run/troupe/commit/f7a86cd5b5e86677b2ab7af7fc7ad0708712028f))
* **release:** release the protocol on its own, and record its version in the troupe package ([#140](https://github.com/troupe-run/troupe/issues/140)) ([6a2bcaa](https://github.com/troupe-run/troupe/commit/6a2bcaab7c578487e1cf33e994d7a36c31ff1832))
* **runner-protocol:** close run events, results and runner errors ([613ca5b](https://github.com/troupe-run/troupe/commit/613ca5bfc2f7af4519adb47f98d9a50c6826e0db))
* **runner-protocol:** runner options are an extension point the runner fills ([84b46c3](https://github.com/troupe-run/troupe/commit/84b46c3e251cfcf29e1702fc77bcb00e02760d04))
* **runner:** run/start carries the run's direction and the actor's character ([#60](https://github.com/troupe-run/troupe/issues/60)) ([7eece31](https://github.com/troupe-run/troupe/commit/7eece31b55367f2ec6b7a2b022b2aeffed361500))
* **runners:** the runner contract is version 0, the draft ([69d6c27](https://github.com/troupe-run/troupe/commit/69d6c276db144bd47bdfb39e69d2ac3e03bc6144))
* **runs:** logs --follow subscribes to the store instead of polling ([c7fc057](https://github.com/troupe-run/troupe/commit/c7fc0579e6b41f5a2b4a6e852169a4aa063f3115))
* **runs:** perform in a worktree by default, and diff, accept or discard its changes ([#51](https://github.com/troupe-run/troupe/issues/51)) ([564f0cc](https://github.com/troupe-run/troupe/commit/564f0cc31f630c7ddb1a7a7d8bdca9a575a0b6c0))
* **runs:** perform runs one actor and records the run in its own stream ([351704d](https://github.com/troupe-run/troupe/commit/351704d70f1f52f1d5e543eaab99d8f7622c205a))
* **runs:** perform runs the Claude Code runner, with only the variables it needs ([#55](https://github.com/troupe-run/troupe/issues/55)) ([5df903a](https://github.com/troupe-run/troupe/commit/5df903aaab300868c0674f2a8c257c5460fde97a))
* **runs:** read a run's reported runner from its init, and clones from WorktreeMade ([d191a01](https://github.com/troupe-run/troupe/commit/d191a013bdf6bedd056be7b5584e4728467d7c08))
* **runs:** read runs back with status and logs, from projections ([16a6bc6](https://github.com/troupe-run/troupe/commit/16a6bc61620d4aff749567169c30c9e39250d0c1))
* **runs:** record a run's start before its worktree and runner ([#154](https://github.com/troupe-run/troupe/issues/154)) ([24fc755](https://github.com/troupe-run/troupe/commit/24fc75568b514fbfc69654acced7fd1553203905))
* **runs:** record a run's workspace and captured changes, and accepting or discarding them ([#51](https://github.com/troupe-run/troupe/issues/51)) ([264cb92](https://github.com/troupe-run/troupe/commit/264cb927244ac8991f42ac6aaaec4bd5a43496ce))
* **runs:** record a worktree's clone mechanisms in Run.WorktreeMade ([c71c758](https://github.com/troupe-run/troupe/commit/c71c7581aa7319248785bf09d0198ae8c57f3ffd))
* **runs:** record and report runs without nulls ([9cc2f37](https://github.com/troupe-run/troupe/commit/9cc2f37cfc11cbf19c5c96504278def720a7e030)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
* **runs:** show followed events as they're recorded, and test a real Ctrl-C on Windows ([b751e1b](https://github.com/troupe-run/troupe/commit/b751e1ba951fceac2fb4b3575c9ba8c8e0ea26eb))
* **schemas:** troupe carries the protocol's schemas, and reads a runner's from the installed runner ([#60](https://github.com/troupe-run/troupe/issues/60)) ([5ea49b2](https://github.com/troupe-run/troupe/commit/5ea49b24d218e5c0c7ebbb849dbab45a6f7950d0))
* **scripts:** declare which paths need which part of the check ([e9f7db5](https://github.com/troupe-run/troupe/commit/e9f7db51ac9395253c9752815a8d85621431e7e8))
* **settings:** add a settings seam and mark_merges_resolved ([f078b46](https://github.com/troupe-run/troupe/commit/f078b46c392d43b0d99db140d7aa35ee991c385f))
* **stages:** add the stage port and a local stage that refuses unless policy allows it ([9908c0c](https://github.com/troupe-run/troupe/commit/9908c0c15ba6170edd623ba519c1469b4108558f))
* **store:** encode and read segment lines with content-hash ids ([955f753](https://github.com/troupe-run/troupe/commit/955f7539a169081c7cbbe127ed673a1ce2d0445a))
* **store:** record events in per-session segments with a local order ([1c82430](https://github.com/troupe-run/troupe/commit/1c82430b82cdd85d70801db2f24a1bb3a1399c58))
* **theatre:** keep troupe's patterns in .gitignore and .gitattributes without touching a person's lines ([#60](https://github.com/troupe-run/troupe/issues/60)) ([ca2b154](https://github.com/troupe-run/troupe/commit/ca2b15489db37bceb6209db21fed368b05226783))
* **vcs:** cache the branch and HEAD behind a token that sees every move ([#75](https://github.com/troupe-run/troupe/issues/75)) ([cceeee4](https://github.com/troupe-run/troupe/commit/cceeee41e40d618031ef6818922977bf1d4d0b72))
* **vcs:** make, fill, diff, apply and remove a run's worktree, and snapshot shared git state ([#51](https://github.com/troupe-run/troupe/issues/51)) ([6ba3ac5](https://github.com/troupe-run/troupe/commit/6ba3ac5c3381014ba7abe5c2b5ee1b77729885cc))
* **vcs:** mark a merged path resolved through the VCS port ([eabe7a1](https://github.com/troupe-run/troupe/commit/eabe7a12eccaba026fd7b8af1fb2268cb2747590))
* **vcs:** read branch, HEAD and what is committed through a VCS port ([4729252](https://github.com/troupe-run/troupe/commit/4729252008441c7fe66abb20330ca8e9f8f1e686))
* **vcs:** read the branch and HEAD again just after a change ([#75](https://github.com/troupe-run/troupe/issues/75)) ([54d9a94](https://github.com/troupe-run/troupe/commit/54d9a941dfe8c207d687522e3d31be30262a2d6e))
* **vcs:** report the sides a merge combined into a path ([#141](https://github.com/troupe-run/troupe/issues/141)) ([dbc699f](https://github.com/troupe-run/troupe/commit/dbc699f0c3043e07e65f5a110e948e899016f63d))
* **workspace:** add the event-store adapter packages and their import contracts ([6746785](https://github.com/troupe-run/troupe/commit/67467850696f4da6df5330c47e78133cdae4a38f))


### Bug Fixes

* **cli:** a trailing `--` with nothing after it changes nothing ([fe9a0d9](https://github.com/troupe-run/troupe/commit/fe9a0d97448e6767291ae4d9dd4f86c34c8e8d09))
* **cli:** leave a usage error's command out before any command ([1471634](https://github.com/troupe-run/troupe/commit/1471634ed624aa21233835eb3cffb879288258db)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
* **cli:** print the troupe: prefix once on argparse's usage errors ([f0a639a](https://github.com/troupe-run/troupe/commit/f0a639ab918940f15824559d947d6df96520bdbf)), closes [#53](https://github.com/troupe-run/troupe/issues/53)
* **cli:** take dash-leading text with a space as an option's value ([b045773](https://github.com/troupe-run/troupe/commit/b045773b89f10ca102083847dd6f8fb34c7a6896)), closes [#53](https://github.com/troupe-run/troupe/issues/53)
* **config:** a line whose first writes start from different values is a change ([23e6b37](https://github.com/troupe-run/troupe/commit/23e6b376d87740b0a452e4bdda8fd7663585af69))
* **config:** contest what's beneath a point when nothing at its frontier stays in ([04d7f23](https://github.com/troupe-run/troupe/commit/04d7f23b678470eb4173fd4f9779e070a4e8f674))
* **config:** let the config set resolving a conflict rewrite every merged file ([#141](https://github.com/troupe-run/troupe/issues/141)) ([0316845](https://github.com/troupe-run/troupe/commit/0316845b71523ef854216b53f76a7e58bd62ec5f))
* **config:** show each side's value in a conflict, and say how to take a side of a file git left conflicted ([#60](https://github.com/troupe-run/troupe/issues/60)) ([d8720ef](https://github.com/troupe-run/troupe/commit/d8720ef222caff50031d8c708dc9791e0e055f05))
* **event-store:** stopping a subscription waits for its thread, bounded ([1ecd201](https://github.com/troupe-run/troupe/commit/1ecd201eca7ed8d60ae8e7a1a5a51a09e793201e))
* **events:** pad lineage years to four digits on every platform ([3fb1694](https://github.com/troupe-run/troupe/commit/3fb1694762b044687ca6d6df295266ef1063e592))
* **platform:** a wait that times out has always been announced ([d7c6232](https://github.com/troupe-run/troupe/commit/d7c62322fa5ce3863566175e0ba608dad4a463b8))
* **platform:** a watch wait returns no earlier than its timeout, on every platform ([37c23ff](https://github.com/troupe-run/troupe/commit/37c23ff61df516be9d14372cabeb8cefd55d57d8))
* **platform:** a watched directory removed on Windows is missing, not unwatchable ([a76a4b5](https://github.com/troupe-run/troupe/commit/a76a4b5b87f779857c6d3b60362691e03602260d))
* **platform:** describe Windows error codes of 2**31 and above ([5cb7ad0](https://github.com/troupe-run/troupe/commit/5cb7ad0871734dc9e934144e6aa040c1a7816365))
* **platform:** end waits once children exit; start Windows suspended ([2b43f9a](https://github.com/troupe-run/troupe/commit/2b43f9ad01ec8f1d6692740dcdedbf624582e33e))
* **platform:** is_running says whether a process has ended, on every platform ([7ec3d6a](https://github.com/troupe-run/troupe/commit/7ec3d6ab6ba4683313a26808cd536a0c862295b1)), closes [#92](https://github.com/troupe-run/troupe/issues/92)
* **platform:** the interrupt test's child counts in its handler, not prints ([b86950b](https://github.com/troupe-run/troupe/commit/b86950bccc1f3cc1a8945bba6289b95b06c5109e))
* **runners:** record a run as killed only when troupe's kill ended it ([749212a](https://github.com/troupe-run/troupe/commit/749212a9fb3de3c654dfed83389bf9253d91d682)), closes [#86](https://github.com/troupe-run/troupe/issues/86)
* **runners:** take a run's exit code from the wait that ended it ([319eb40](https://github.com/troupe-run/troupe/commit/319eb40171eb3250fca5146b6e070d9463f4596a)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
* **runs:** reload a run whose Run.WorktreeMade couldn't be recorded ([dd6189b](https://github.com/troupe-run/troupe/commit/dd6189bc719b2a85b119c43b5c047efe2b598490))
* **schemas:** tell a missing plugin's user how to reinstall, not to uv sync a checkout ([#195](https://github.com/troupe-run/troupe/issues/195)) ([2b42965](https://github.com/troupe-run/troupe/commit/2b42965a88a629806a068eed07930b68d09067eb))
* **vcs:** don't refuse a theatre whose commit holds a file git would normalise ([#51](https://github.com/troupe-run/troupe/issues/51)) ([526682b](https://github.com/troupe-run/troupe/commit/526682b9e0d9425960d795a0ac8dc45d6f8d1caa))


### Documentation

* bring the user docs from the website, checked for the site's front matter ([d70dfc7](https://github.com/troupe-run/troupe/commit/d70dfc71fa09e1e133adff57a4b4cf701a2024b2)), closes [#123](https://github.com/troupe-run/troupe/issues/123)
* describe troupe as agreed with the owner ([f53be09](https://github.com/troupe-run/troupe/commit/f53be0936eba3ee8e49a31f632746e160b022481))
* **events:** describe the event store, and measure a cold read of 10,000 segments ([a7bd68b](https://github.com/troupe-run/troupe/commit/a7bd68b3820709769f77ffef84deb549f6e28d93))
* move the contributor docs to contributing/ ([296599d](https://github.com/troupe-run/troupe/commit/296599dbfb5893db05dae8c6ab7ec89518b3befb)), closes [#123](https://github.com/troupe-run/troupe/issues/123)
* **openspec:** archive config-merge-order, syncing the config spec ([d247a60](https://github.com/troupe-run/troupe/commit/d247a608ffb25d924ea48105e7f482cac9d8acc4))
* **openspec:** archive omit-nulls and sync its specs ([31ccdfe](https://github.com/troupe-run/troupe/commit/31ccdfe80c331e316b6c72c166a159cd61357e3c)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
* write the 22 placeholder pages, as built behaviour or decided intent ([00ee141](https://github.com/troupe-run/troupe/commit/00ee1410b0ddf784faeb5825d4cc8a2d86428d93)), closes [#123](https://github.com/troupe-run/troupe/issues/123)
* write the changelog page as links to the changelogs release-please writes ([435a2ed](https://github.com/troupe-run/troupe/commit/435a2ed87594e27d827986f032f470deac6b3d20)), closes [#123](https://github.com/troupe-run/troupe/issues/123)
