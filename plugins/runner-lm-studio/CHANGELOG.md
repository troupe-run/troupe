# Changelog

## 0.1.0 (2026-11-14)


### Features

* **lm-studio:** stop at the context limit, and warn it won't compact ([a45df7b](https://github.com/troupe-run/troupe/commit/a45df7b2516f79aa9c7c11bcc439ebb10c1d6df6))
* **runner-lm-studio:** run actors on LM Studio through lmstudio ([117f688](https://github.com/troupe-run/troupe/commit/117f688024e3d7e39f6c8c1e8e896ac4b0337319)), closes [#291](https://github.com/troupe-run/troupe/issues/291)
* **runner-lm-studio:** say when a retry wasn't safe, with notRetried ([025928d](https://github.com/troupe-run/troupe/commit/025928d48096eda9e5ea4206193fee4f8a2f5137))
* **runtimes:** add an in-process runtime with no endpoint ([3e9ecbd](https://github.com/troupe-run/troupe/commit/3e9ecbdd7e34458cccb6b620b02ae68f87bf6411))


### Bug Fixes

* **runner-lm-studio:** count a round's calls when the round ends ([2782b18](https://github.com/troupe-run/troupe/commit/2782b18b98fe5d3d54242144f74405212b0b0c3a))
* **runner-lm-studio:** end a failed reconnect as network, bound the check ([16917cc](https://github.com/troupe-run/troupe/commit/16917cccf3a029ead6037777396bbaab069adc9e)), closes [#291](https://github.com/troupe-run/troupe/issues/291)
* **runner-lm-studio:** let a run finish ok on its last allowed round ([6e59d7a](https://github.com/troupe-run/troupe/commit/6e59d7a9e53b09caab025ca4f4ebe06e6d07aeb8)), closes [#291](https://github.com/troupe-run/troupe/issues/291)
* **runner-lm-studio:** stop act() between rounds from its callback ([e69ee71](https://github.com/troupe-run/troupe/commit/e69ee7125543c1ca3a9b6d8408c4d8cceafe23fd)), closes [#291](https://github.com/troupe-run/troupe/issues/291)
