# Changelog

## 0.1.0 (2026-10-31)


### ⚠ BREAKING CHANGES

* **events:** segments written before this change have no "protocol" in their header and are refused as malformed records.
* **runs:** segments, run events and client messages no longer carry nulls, and readers refuse them; there are no theatres to migrate.
* **runners:** the runner contract is version 0, the draft
* **protocol:** error and notice detail keys that were snake_case are now camelCase (exitCode, limitBytes, waitedSeconds and the rest), and events.unknown-format's format detail is JSON text. Nothing outside this repository reads them.

### Features

* **events:** detect forked streams and settle them with an event that names every head ([b33eb25](https://github.com/troupe-run/troupe/commit/b33eb25f5e426e62cc87fc77f5be3fae0df61dc9))
* **events:** let an aggregate read a forked stream whole and settle it with its next change ([#60](https://github.com/troupe-run/troupe/issues/60)) ([6a5696f](https://github.com/troupe-run/troupe/commit/6a5696f17a6f607c0f9584ecd245686487a59744))
* **events:** name the protocol that wrote a segment in its header, and report it in --version ([#140](https://github.com/troupe-run/troupe/issues/140)) ([ddf0c0b](https://github.com/troupe-run/troupe/commit/ddf0c0bba65fe5ba80e5a1bdac1c30d83b1a6af9))
* **events:** subscriptions deliver other writers' events as they're recorded ([f8f9416](https://github.com/troupe-run/troupe/commit/f8f9416b65cb0ccb19a39689572921a00d5f6b68))
* **protocol:** catalogue every error and notice code with closed details ([36f8241](https://github.com/troupe-run/troupe/commit/36f824164ede66cba5128ab7f79c2fb25a7af7c0))
* **runners:** the runner contract is version 0, the draft ([69d6c27](https://github.com/troupe-run/troupe/commit/69d6c276db144bd47bdfb39e69d2ac3e03bc6144))
* **runs:** record and report runs without nulls ([9cc2f37](https://github.com/troupe-run/troupe/commit/9cc2f37cfc11cbf19c5c96504278def720a7e030)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
* **schemas:** troupe carries the protocol's schemas, and reads a runner's from the installed runner ([#60](https://github.com/troupe-run/troupe/issues/60)) ([5ea49b2](https://github.com/troupe-run/troupe/commit/5ea49b24d218e5c0c7ebbb849dbab45a6f7950d0))
* **store:** encode and read segment lines with content-hash ids ([955f753](https://github.com/troupe-run/troupe/commit/955f7539a169081c7cbbe127ed673a1ce2d0445a))
* **store:** record events in per-session segments with a local order ([1c82430](https://github.com/troupe-run/troupe/commit/1c82430b82cdd85d70801db2f24a1bb3a1399c58))
* **theatre:** keep troupe's patterns in .gitignore and .gitattributes without touching a person's lines ([#60](https://github.com/troupe-run/troupe/issues/60)) ([ca2b154](https://github.com/troupe-run/troupe/commit/ca2b15489db37bceb6209db21fed368b05226783))
* **vcs:** read the branch and HEAD again just after a change ([#75](https://github.com/troupe-run/troupe/issues/75)) ([54d9a94](https://github.com/troupe-run/troupe/commit/54d9a941dfe8c207d687522e3d31be30262a2d6e))
* **workspace:** add the event-store adapter packages and their import contracts ([6746785](https://github.com/troupe-run/troupe/commit/67467850696f4da6df5330c47e78133cdae4a38f))


### Bug Fixes

* **event-store:** a stopped subscription delivers nothing more ([2b210e8](https://github.com/troupe-run/troupe/commit/2b210e806c170a7c271eb58b576709f5ad1ec3d7))
* **event-store:** stopping a subscription waits for its thread, bounded ([1ecd201](https://github.com/troupe-run/troupe/commit/1ecd201eca7ed8d60ae8e7a1a5a51a09e793201e))
* **events:** don't take a late or pre-watch event for a missed write ([ef2142d](https://github.com/troupe-run/troupe/commit/ef2142d2d853878082bab914d138721332fdcb4c))
* **protocol:** catalogue events.subscription-polling from [#74](https://github.com/troupe-run/troupe/issues/74) ([6da20b8](https://github.com/troupe-run/troupe/commit/6da20b81ba4fb27663fe72b0941f49b0279803c6))


### Documentation

* move the contributor docs to contributing/ ([296599d](https://github.com/troupe-run/troupe/commit/296599dbfb5893db05dae8c6ab7ec89518b3befb)), closes [#123](https://github.com/troupe-run/troupe/issues/123)
* **openspec:** archive fix-racing-writers-test ([31809fb](https://github.com/troupe-run/troupe/commit/31809fb705a8faf4c5964c8ee1084ef31c529128))
* **openspec:** archive omit-nulls and sync its specs ([31ccdfe](https://github.com/troupe-run/troupe/commit/31ccdfe80c331e316b6c72c166a159cd61357e3c)), closes [#76](https://github.com/troupe-run/troupe/issues/76)
