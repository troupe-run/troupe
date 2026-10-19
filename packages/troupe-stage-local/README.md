# troupe-stage-local

troupe's local stage: it runs an actor as a process on the host, with the theatre's root as its workspace. A
process on the host can touch anything the person running troupe can, so the local stage enforces none of an
actor's effects. It admits an actor only when the policy setting `allow_unenforced_local_stage` allows it, and every
run it admits records in its lineage that its effects weren't enforced (decision
[#3](https://github.com/troupe-run/troupe/issues/3)). It implements the `Stage` port in `troupe.core.stages` and is
registered as `local` in the `troupe.stages` entry point group, so troupe finds it by name and never imports it
directly. See [contributing/runs.md](../../contributing/runs.md).
