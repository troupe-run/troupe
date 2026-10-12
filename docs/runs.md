# Runs

`troupe perform` runs one actor and records the run in the theatre's event store. `troupe status` and `troupe logs`
read runs back. This page describes runs as built by the `perform-status-logs` change (#36); the decisions behind it
are #3 (what a local stage does about declared effects) and #14 (no run server yet: commands and queries are
messages in `protocol/`).

## Stages

A **stage** is where an actor runs. Whether troupe can enforce what the actor may touch (its declared effects)
depends on the stage. Stages are found by name (the `troupe.stages` entry point group); troupe never imports one.

Before a runner starts, the stage **admits** the actor or refuses it. A refused actor isn't run, and nothing is
recorded: no event, no artifact.

### The local stage

The local stage (`troupe-stage-local`, registered as `local`) runs the actor as a process on your machine, with the
theatre's root as its workspace. It's the only stage so far, and the default.

**It enforces nothing.** A process on your machine can write any file and reach any host you can. So the local stage
treats every actor's effects as unenforceable, including an actor that declares none: "no effects" is a claim it
can't check either. It refuses every actor with `stage.effects-unenforced` unless the policy setting
`allow_unenforced_local_stage` is true (decision [#3](https://github.com/troupe-run/troupe/issues/3), option C).

When policy allows it, every event the run records says so in its lineage:

```json
"stage": {"name": "local", "effects": "unenforced",
          "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"}}
```

A run's effect check (`--expect`) isn't enforcement. It checks after the run that the actor produced what it was
for, and a passing check doesn't make the run's effects count as enforced. A stage that can enforce effects, such
as a Docker stage, comes later.

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

## Notices and errors

| Error | When |
|---|---|
| `theatre.not-found` | No directory from here upwards holds `.troupe/` |
| `runner.unknown` | `--runner` names a runner troupe doesn't know |
| `stage.unknown` | No stage of that name is installed |
| `stage.effects-unenforced` | The stage can't enforce the actor's effects, and policy doesn't allow running it anyway |
| `policy.invalid-value` | A policy variable is set to something other than `true` or `false` |

## Defaults

Every limit and default runs use has its default in `troupe.core.defaults`.

| Setting | Default | What it is |
|---|---|---|
| `ALLOW_UNENFORCED_LOCAL_STAGE` | false | The policy setting `allow_unenforced_local_stage`, when nothing sets it |
