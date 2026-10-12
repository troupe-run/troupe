# troupe-artifacts-local

troupe's local artifact store: run artifacts, such as raw transcripts, kept as content-addressed files in a
directory and referenced by `sha256:<hex>`. It implements the `ArtifactStore` port in `troupe.core.artifacts` and is
registered as `local` in the `troupe.artifacts` entry point group, so troupe finds it by name and never imports it
directly. See [docs/runners.md](../../docs/runners.md#where-transcripts-are-kept).
