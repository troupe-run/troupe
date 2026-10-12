# Runs

`troupe perform` runs one actor and records the run in the theatre's event store. `troupe status` and `troupe logs`
read runs back. This page describes runs as built by the `perform-status-logs` change (#36); the decisions behind it
are #3 (what a local stage does about declared effects) and #14 (no run server yet: commands and queries are
messages in `protocol/`).

## Policy

Policy settings decide what troupe may do, whoever asks. troupe reads them through one place (`troupe.core.policy`),
and never from a command's request, so no client can loosen them.

| Setting | Default | What it allows |
|---|---|---|
| `allow_unenforced_local_stage` | `false` | Running an actor on a stage that can't enforce its declared effects, such as the local stage |

**Setting it, for now.** Until config brings policy files (#8), the only way to set a policy is an environment
variable: `TROUPE_POLICY_` and the setting's name in capitals. This is interim, and config replaces it.

```console
export TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true
```

- The value must be exactly `true` or `false`. Anything else (`yes`, `TRUE`, `1`) fails the command with
  `policy.invalid-value`; it never falls back to the default.
- Unset or empty means the default.
- Lineage records where the value came from (`env` or `default`) for every run it allowed.

## Defaults

Every limit and default runs use has its default in `troupe.core.defaults`.

| Setting | Default | What it is |
|---|---|---|
| `ALLOW_UNENFORCED_LOCAL_STAGE` | false | The policy setting `allow_unenforced_local_stage`, when nothing sets it |
