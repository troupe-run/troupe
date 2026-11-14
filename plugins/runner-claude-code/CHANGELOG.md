# Changelog

## [0.2.0](https://github.com/troupe-run/troupe/compare/troupe-runner-claude-code-v0.1.0...troupe-runner-claude-code-v0.2.0) (2026-11-14)


### ⚠ BREAKING CHANGES

* **runner-protocol:** a runner that predates this rejects run/start's new onContextFull field. The contract is version 0, and every runner is in this repository.
* **claude-code:** a Claude Code run whose context fills now ends with an error result instead of compacting. A long run that got through by compacting fails until its task is split or its actor opts in ([#310](https://github.com/troupe-run/troupe/issues/310)).
* **runner-protocol:** a runner's result with status error must carry a reason from the contract's list, and an ok result must not; troupe refuses either as a protocol violation, and run.error-result's details now require the reason. Every runner that speaks the contract is in this repository and is updated here; there are no recorded theatres to migrate.

### Features

* carry declared effects and a scratch directory to runners ([ce62005](https://github.com/troupe-run/troupe/commit/ce6200565f60b7a1b6661f2061aa7994cedb7d86))
* **claude-code:** capture fixtures through the runner's own rules ([2e25dce](https://github.com/troupe-run/troupe/commit/2e25dce0494625c266e59da14c113fb9c888f60d))
* **claude-code:** Claude Code compacts when the run says compact ([dbd05a2](https://github.com/troupe-run/troupe/commit/dbd05a2afb9e05d1dc4d9dcda811ccc26e77595e))
* **claude-code:** map Claude Code's context limit to context-length ([daa5baa](https://github.com/troupe-run/troupe/commit/daa5baa20c232941a42aefa9dd82b7788a9481f0))
* **claude-code:** translate declared effects into permission rules ([7ed5cf1](https://github.com/troupe-run/troupe/commit/7ed5cf1e6ec9596af2fafde03e392a6084546b46))
* **claude-code:** turn off Claude Code's automatic compaction ([d2524d0](https://github.com/troupe-run/troupe/commit/d2524d01cc119a4e15860559ba74b8a6d3e26548))
* **lm-studio:** stop at the context limit, and warn it won't compact ([a45df7b](https://github.com/troupe-run/troupe/commit/a45df7b2516f79aa9c7c11bcc439ebb10c1d6df6))
* **runner-protocol:** a failed result says why, in a reason ([3dcfe3f](https://github.com/troupe-run/troupe/commit/3dcfe3f344d1621109761bedbe5eda5ed773b5a7)), closes [#296](https://github.com/troupe-run/troupe/issues/296)
* **runner-protocol:** report the model that served a run ([409a5f9](https://github.com/troupe-run/troupe/commit/409a5f9c82361e8134d88816010d98e47419defc)), closes [#295](https://github.com/troupe-run/troupe/issues/295)
* **runner-protocol:** run/start says whether the run may compact ([21851c3](https://github.com/troupe-run/troupe/commit/21851c36e6b9e74a5cf7715325580119fe6b8cf1))

## 0.1.0 (2026-11-01)


### Features

* **runner-claude-code:** build Claude Code's command line from fixed flags and private files ([#55](https://github.com/troupe-run/troupe/issues/55)) ([3d51844](https://github.com/troupe-run/troupe/commit/3d51844e5ccc2989f7516e5ff58405fa3c2fa6eb))
* **runner-claude-code:** map Claude Code's stream-json onto run events ([#55](https://github.com/troupe-run/troupe/issues/55)) ([08ec6d6](https://github.com/troupe-run/troupe/commit/08ec6d692a76d1ca041b10c485aaf4297960866c))
* **runner-claude-code:** publish and check the runner's options ([#55](https://github.com/troupe-run/troupe/issues/55)) ([fbefd70](https://github.com/troupe-run/troupe/commit/fbefd7064cf8f3510b9c0172f54dedc63cf99d8a))
* **runner-claude-code:** run Claude Code through the runner contract ([#55](https://github.com/troupe-run/troupe/issues/55)) ([64acc78](https://github.com/troupe-run/troupe/commit/64acc7896a8476022c91fbe3aaaed6fe0e698528))
* **runner-claude-code:** scaffold the plugin and its OS seam ([#55](https://github.com/troupe-run/troupe/issues/55)) ([d5df603](https://github.com/troupe-run/troupe/commit/d5df60316e74f71202769793f17718092d9e1232))
* **runs:** perform runs the Claude Code runner, with only the variables it needs ([#55](https://github.com/troupe-run/troupe/issues/55)) ([5df903a](https://github.com/troupe-run/troupe/commit/5df903aaab300868c0674f2a8c257c5460fde97a))


### Bug Fixes

* **runner-claude-code:** give the fixtures' results the cache counters the contract maps ([#55](https://github.com/troupe-run/troupe/issues/55)) ([a5f365d](https://github.com/troupe-run/troupe/commit/a5f365df146d27515c8baed20dd305af2d4b79d2))
* **runner-claude-code:** start Claude Code suspended on Windows, so its children are in its job ([#55](https://github.com/troupe-run/troupe/issues/55)) ([9fac2f6](https://github.com/troupe-run/troupe/commit/9fac2f694c17e31b946a09e7177ec0ba5a6c94ba))
* **runner-claude-code:** wait for Claude Code's job to empty after terminating it ([#55](https://github.com/troupe-run/troupe/issues/55)) ([b417db2](https://github.com/troupe-run/troupe/commit/b417db2923382b9fcdc4a18386f2838c10f15778))
* **runner-claude-code:** wait on each of the job's processes after terminating it ([#55](https://github.com/troupe-run/troupe/issues/55)) ([e16d5c8](https://github.com/troupe-run/troupe/commit/e16d5c8a545149f3b3df50c32424e3f5b838bfa6))
