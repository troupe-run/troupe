# troupe-runner-mistralrs

troupe's in-process runner: it loads a GGUF model inside its own process with
[mistral.rs](https://github.com/EricLBuehler/mistral.rs)'s Python package, `mistralrs`, and drives it with troupe's
own tool loop. There's no server and no network. Install it with `troupe-run[mistralrs]`, and point the built-in
`mistralrs` runtime at a model file with `TROUPE_RUNTIME_MISTRALRS_MODEL`.

Spec: `openspec/specs/mistralrs-runner/spec.md`.
