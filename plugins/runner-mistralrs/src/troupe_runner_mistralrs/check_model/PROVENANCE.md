# The check model: stories260K.gguf

The mistralrs runner carries this 1.2 MB model to check, before it acknowledges a run on macOS, that mistral.rs can
compile its Metal kernels under the Python it runs in. The tests use it to run the real engine on every OS without
downloading a model (in-process-runner design D4, D10). It writes short children's stories. It has no chat template
and can't call tools, so it never plays an actor.

| | |
|---|---|
| File | `stories260K.gguf` |
| SHA-256 | `270cba1bd5109f42d03350f60406024560464db173c0e387d91f0426d3bd256d` |
| Size | 1,185,376 bytes |
| Weights | `stories260K`, from [karpathy/tinyllamas](https://huggingface.co/karpathy/tinyllamas) (the llama2.c project), MIT |
| GGUF conversion | `tinyllamas/stories260K.gguf`, from [ggml-org/models](https://huggingface.co/ggml-org/models) (the llama.cpp project), MIT |
| Fetched | 2026-11-14 |

Both licences are in [`LICENSE`](LICENSE), beside this file. A test checks the file's SHA-256 against this record.
