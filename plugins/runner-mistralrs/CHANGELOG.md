# Changelog

## 0.1.0 (2026-11-19)


### Features

* **init:** warm a runner's engine before its first run ([23662dc](https://github.com/troupe-run/troupe/commit/23662dc55a76e351ede838b9bdd1772b0d955062))
* **runner-mistralrs:** add the in-process runner's package and engine ([50518ab](https://github.com/troupe-run/troupe/commit/50518abcf64487da09a7a1f0131272e6e454915b))
* **runner-mistralrs:** run the conversation, with tests and docs ([096e135](https://github.com/troupe-run/troupe/commit/096e135cc0c099600146355d63cebab06d6c9daf))
* **runners:** end every runner through the SDK's exit_now, so coverage can save ([217e083](https://github.com/troupe-run/troupe/commit/217e083b5bc9d36dea3b2ccc84277e9e20889b9a)), closes [#443](https://github.com/troupe-run/troupe/issues/443)


### Bug Fixes

* **runner-mistralrs:** act on the review of [#422](https://github.com/troupe-run/troupe/issues/422) ([417a843](https://github.com/troupe-run/troupe/commit/417a843a5849cdc06d41d7533b28a75c828ee113))
* **runner-mistralrs:** check the answer comes before the load ([2f7e3e5](https://github.com/troupe-run/troupe/commit/2f7e3e5e4a71f6170938190a2ab729c106eebec2))
* **runner-mistralrs:** refuse a huge integer temperature as invalid ([55902b2](https://github.com/troupe-run/troupe/commit/55902b25132b3147c5713fd3c35af8aa8abba48e))
* **runners:** clean a tool call's id and OpenAI's non-stream body ([45ab433](https://github.com/troupe-run/troupe/commit/45ab433c4f9fd08ee3c0b2d8c21c5e4dd229381f))
* **runners:** record each lone surrogate replaced, in a context event ([ae9f7a6](https://github.com/troupe-run/troupe/commit/ae9f7a6f3abe27c9d7863c1f5c56a38b23a64cea))
* **runners:** refuse a second initialize with already-initialized ([ad1769b](https://github.com/troupe-run/troupe/commit/ad1769bd880fbb996b1fc94fafcfdd7aad89923e))
* **runners:** write lone surrogates as U+FFFD, never as an escape ([fef4bd5](https://github.com/troupe-run/troupe/commit/fef4bd5c222b1c13014b8e14bf3692d130624d83))
