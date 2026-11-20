# Changelog

## [0.2.0](https://github.com/troupe-run/troupe/compare/troupe-run-v0.1.0...troupe-run-v0.2.0) (2026-11-20)


### ⚠ BREAKING CHANGES

* **bundle:** troupe 0.2.0 and troupe-plugin-sdk 0.1.0 and troupe-runner-anthropic 0.1.0 and troupe-runner-claude-code 0.2.0 and troupe-runner-ollama 0.1.0 and troupe-runner-openai 0.1.0 and troupe-runner-scripted 0.2.0 have breaking changes: see packages/troupe/CHANGELOG.md and packages/troupe-plugin-sdk/CHANGELOG.md and plugins/runner-anthropic/CHANGELOG.md and plugins/runner-claude-code/CHANGELOG.md and plugins/runner-ollama/CHANGELOG.md and plugins/runner-openai/CHANGELOG.md and plugins/runner-scripted/CHANGELOG.md.
* **openai:** the OpenAI runner is troupe-run's openai extra, no longer in the base install; install troupe-run[openai] or [all].
* **runner-ollama:** troupe-run no longer installs the Ollama runner by default; install troupe-run[ollama] (or troupe-run[all]).

### Features

* **bundle:** runners with libraries are extras of troupe-run ([8e2d44d](https://github.com/troupe-run/troupe/commit/8e2d44d603a5f130f844c3a35ab9098bfa65ad68)), closes [#333](https://github.com/troupe-run/troupe/issues/333)
* **bundle:** ship 12 component releases ([7fb3998](https://github.com/troupe-run/troupe/commit/7fb39984b7cf5b81255aeb9d535eda87db3a5ba6))
* **installation:** check and document troupe-run's extras ([b5d0f7c](https://github.com/troupe-run/troupe/commit/b5d0f7c7190051f63cedf7304226ab8ee24cbfcd)), closes [#333](https://github.com/troupe-run/troupe/issues/333)
* **openai:** send the OpenAI runner's requests through openai ([3a732a3](https://github.com/troupe-run/troupe/commit/3a732a38830a9f934ca0941d9038e62fa689667c)), closes [#331](https://github.com/troupe-run/troupe/issues/331)
* **runner-anthropic:** add a runner for the Anthropic Messages API ([0d3bd99](https://github.com/troupe-run/troupe/commit/0d3bd995def2ce4d24be238614864170fb109465))
* **runner-lm-studio:** run actors on LM Studio through lmstudio ([117f688](https://github.com/troupe-run/troupe/commit/117f688024e3d7e39f6c8c1e8e896ac4b0337319)), closes [#291](https://github.com/troupe-run/troupe/issues/291)
* **runner-mistralrs:** add the in-process runner's package and engine ([50518ab](https://github.com/troupe-run/troupe/commit/50518abcf64487da09a7a1f0131272e6e454915b))
* **runner-ollama:** install the Ollama runner as troupe-run[ollama] ([0760a38](https://github.com/troupe-run/troupe/commit/0760a383bdb64680106cfa4fcb83d476cadbf875))
* **runner-ollama:** scaffold the plugin and check its options ([#277](https://github.com/troupe-run/troupe/issues/277)) ([0cba57a](https://github.com/troupe-run/troupe/commit/0cba57a88e5ef9a7482c9373c9ae843938b2bdd2))
* **runner-openai-chat:** scaffold the plugin and reach a service ([e4a7d73](https://github.com/troupe-run/troupe/commit/e4a7d73e00342918de820caa00e2da1f79a91972))
* **runner-openai:** rename to openai, ship it, and give it an audition ([f4cedac](https://github.com/troupe-run/troupe/commit/f4cedac9f3ce3e90af0b397c62a4910be6f3b997))
* **runners:** remove the LM Studio runner before 0.2.0 ([26e9b7a](https://github.com/troupe-run/troupe/commit/26e9b7ac949237f3844a45513473525b63169b75))


### Bug Fixes

* **runner-openai:** act on the split review of the whole PR ([b3f1910](https://github.com/troupe-run/troupe/commit/b3f191015083b66515900bed2018bbdaa15e3428))

## 0.1.0 (2026-11-01)


### ⚠ BREAKING CHANGES

* **bundle:** troupe 0.1.0 and troupe-artifacts-local 0.1.0 and troupe-runner-scripted 0.1.0 and troupe-store-text 0.1.0 and troupe-vcs-git 0.1.0 have breaking changes: see packages/troupe/CHANGELOG.md and packages/troupe-artifacts-local/CHANGELOG.md and plugins/runner-scripted/CHANGELOG.md and packages/troupe-store-text/CHANGELOG.md and packages/troupe-vcs-git/CHANGELOG.md.

### Features

* **bundle:** ship 9 component releases ([96e980d](https://github.com/troupe-run/troupe/commit/96e980d46e5f936c7bcd93cc1b7b2c4a2fdb9b27))
* **packages:** add troupe-run, the package that installs troupe with what it bundles ([67d13cd](https://github.com/troupe-run/troupe/commit/67d13cd77aec5d3bb1137d7a0a56f8d219f15b55))
