# Changelog

## 0.1.0 (2026-11-07)


### Features

* carry declared effects and a scratch directory to runners ([ce62005](https://github.com/troupe-run/troupe/commit/ce6200565f60b7a1b6661f2061aa7994cedb7d86))
* **runner-ollama:** talk to Ollama and check what it requires ([#277](https://github.com/troupe-run/troupe/issues/277)) ([8893bae](https://github.com/troupe-run/troupe/commit/8893baef1b7a6055235fd1a0da79ea59f216d140))
* **runtimes:** name runtimes in config and hand runs their credential ([5e14751](https://github.com/troupe-run/troupe/commit/5e14751ac70c364326dedd44a2e6b8c8186cb05c))
* **sdk:** check tool paths and declared effects ([3a38e7b](https://github.com/troupe-run/troupe/commit/3a38e7ba4a83a50efbca1799df79f2391b610345))
* **sdk:** run a model's tool calls in the workspace ([e415af7](https://github.com/troupe-run/troupe/commit/e415af71dbbaf97e2a7e5c8cd8b362a60067a3f1))


### Bug Fixes

* **runner-protocol:** say usage.inputTokens leaves out cache tokens ([f6d80b5](https://github.com/troupe-run/troupe/commit/f6d80b50f51845773243bcf22ebbfadbbc985da5))
* **sdk:** give a path outside scratch the same answer everywhere ([130b91e](https://github.com/troupe-run/troupe/commit/130b91e1812e535f70f4bae369d4fe2016386164))
* **sdk:** load only regular files of a bounded size ([c70a494](https://github.com/troupe-run/troupe/commit/c70a494d8de6b3146fe99e3b99fcfa1fde364959))
* **sdk:** never search through a Windows junction out of the workspace ([855a3bf](https://github.com/troupe-run/troupe/commit/855a3bf5f22bfd42f86b1e8358b543c2d738b479))
