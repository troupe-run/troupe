# Design: a failed run records what the audit of its changes found

See [proposal.md](proposal.md) for why. Behaviour is in the deltas to [effects](specs/effects/spec.md),
[actor-runners](specs/actor-runners/spec.md), [runs](specs/runs/spec.md),
[client-protocol](specs/client-protocol/spec.md) and [cli](specs/cli/spec.md).

## Context

- **The effect check is one object.** `perform.effect_check_for` returns `DeclaredEffects` (the audit) or
  `Combined(ExpectedFiles, DeclaredEffects)`, and passes it to `run_actor` as `effect`. The host calls
  `effect.before()` before starting the process, and `effect.after()` only when the result is `ok` and the start
  didn't fail (`host.py`, after the `finally` that ends the process). `derive_outcome` takes the verdict.
- **The audit's findings exist only inside its error.** `DeclaredEffects.after()` computes `outside(...)`, a list of
  `Change`, and wraps it in `effects.outside-declared` with `details.changes`. A passing audit returns no list.
- **A read failure escapes.** `vcs.file_states` can raise; `effect.after()` isn't guarded, so a failure there
  propagates out of `run_actor`, `perform` never records the end, and status shows the run as interrupted.
- **`RunOutcome.to_data()` is `Run.Ended.outcome`.** `perform` adds `changes` (worktree capture) beside it.
  `RunView.summary` builds the client summary from the recorded end; `render_run` prints it for `status <run>`, and
  `logs` prints only `run <id>: <outcome>` after the events.
- **Callers with no workspace.** The conformance suite and the host's unit tests call `run_actor` with
  `NoEffectExpected()` and no VCS.

## Goals / Non-Goals

**Goals:**
- One audit, run in one place, for every run whose runner started, with the same findings whatever the outcome.
- The findings recorded as data in the run's end, so status, logs and later UIs render them from the summary.

**Non-Goals:**
- Changing a failed run's outcome or error. The audit only adds a record beside it.
- Changing `troupe accept` or `troupe discard`: a reviewer reads the audit and decides.
- Re-auditing runs recorded before this change.

## Decisions

### D1. The audit is its own port, passed to the host beside the expected files

`run_actor` takes `audit: Audit` beside `effect: EffectCheck`. `Audit` is `before()` and `after() -> AuditFindings`,
where `AuditFindings` is either `outside: tuple[Change, ...]` (possibly empty) or `error: TroupeError`.
`DeclaredEffects` becomes the `Audit` implementation, and `NoAudit` is the explicit choice for a caller with no
workspace (conformance suite, host unit tests), like `NoEffectExpected`; there's no default. `effect_check_for` is
split: the expected files (`ExpectedFiles` or `NoEffectExpected`) and the audit are built apart, and `perform` passes
both.

The host calls `audit.before()` next to `effect.before()`, before the process starts. After the process has ended,
it calls `audit.after()` whenever the process started, so a start that failed after the process started (handshake
refused, start timeout) is audited too. When the result is `ok`, it calls `effect.after()` as now, and the effect
verdict combines the expected files' verdict and the verdict made from the findings, through `Combined`'s existing
rules, so `effects.outside-declared` and `effects.check-failed` keep their exact messages.

- *Rejected: keep one combined check and add a method to it for the audit alone.* The port would then mix "what the
  run was for" with "what it may change", which already apply at different times; two ports say so.
- *Rejected: `perform` runs the audit itself after `run_actor` returns, for a non-ok outcome only.* Two places would
  run the audit, and an `ok` run's findings would only exist inside its error.
- *Rejected: `audit` defaulting to none.* A caller that forgot it would look identical to one with nothing to audit.

### D2. The findings are recorded as `outcome.audit` in `Run.Ended`

`RunOutcome` gains `audit: AuditFindings | None` (None exactly when the runner never started, or with `NoAudit`), and
`to_data()` writes `audit` into the outcome: `{"outside": [{path, change, needs, to?}, ...]}` or `{"error": {...}}`.
Each entry is the existing `Change.to_data()`, the same shape as `effects.outside-declared`'s `details.changes`.

In `run-ended.schema.json`, `outcome.audit` is a `oneOf` of the two shapes, each closed. The outcome's
`if never-started` branch forbids it; the `else` branch doesn't require it, because an end recorded before this change
has none, and that absence is described in the schema ("Absent: the runner never started, or the end was recorded
before troupe recorded audits").

- *Rejected: an event of its own (`Run.Audited`).* The audit belongs to how the run ended, is read with the end, and
  is written at the same moment; a second event would need its own ordering and failure rules for no gain.
- *Rejected: top-level, beside `changes`.* `changes` is `perform`'s worktree capture; the audit is the host's, part
  of the outcome it derives.
- *Rejected: recording it only for runs that didn't succeed.* A succeeded run's audit is always empty, but recording
  it every time keeps one rule ("present exactly when the runner started") and lets a reader tell an audited success
  from an old record.

### D3. A read failure is recorded, and fails only an `ok` run

`DeclaredEffects.after()` catches `TroupeError` (and wraps anything else as `internal.unexpected`, as `perform` does)
into `AuditFindings(error=...)`. For an `ok` result the verdict from it fails with a new `effects.audit-failed`:
problem "troupe couldn't read the run's workspace to audit its changes: <error's problem>", fix the error's fix and
"then check the changes with troupe diff", `details.error` the error's data. For any other result the outcome is
unchanged and only the end records the error.

This also closes the existing gap where such a failure left an `ok` run without an end. It's in scope because running
the audit after every run would otherwise turn every failed run with an unreadable workspace into an interrupted one.

### D4. The summary carries `audit` as recorded; status and logs render it

`RunView.summary` copies `outcome.audit` into the summary's `audit` when present. `run.schema.json#/$defs/summary`
gains `audit` with the same `oneOf` (defined once in `run-ended.schema.json#/$defs/audit` and referenced), and
`RunSummary` gains `audit: AuditData | None`, a message with `outside` and `error`, refusing both or neither.

`render_run` adds, after the error line:

```
  audit: 2 changes outside the declaration
    src/a.py modified (needs write)
    drafts/a.md moved to docs/a.md (needs move)
```

or `  audit: every change was declared`, or `  audit couldn't run: <code>: <problem>`. Each change uses the existing
`Change.shown()` wording, applied to the recorded data by one function in `render.py`. `logs` prints the same lines
after its `run <id>: <outcome>` line. Runs with no audit print none. `status`'s run list (one line per run) is
unchanged.

### D5. The protocol changes in place

Version 0 changes in place, as for #241: both schemas gain optional fields, so every earlier record still validates.
The packaged copies (`packages/troupe/src/troupe/protocol/`) are regenerated with `scripts/package_schemas.py`.

## Risks / Trade-offs

- **[A theatre run's audit counts others' edits]** → Unchanged from #241, and the more likely for a long run that
  timed out. The audit's findings for a theatre run carry the same "counts every change made there while it ran"
  note when rendered, so a reviewer doesn't read them as the actor's alone.
- **[Auditing a crashed run's half-written workspace]** → The audit only reads file states; it changes nothing, so it
  can't make a failed run worse. Its cost is the same as an ok run's.
- **[The findings repeat the error for an ok run]** → `effects.outside-declared`'s `details.changes` and
  `outcome.audit.outside` hold the same list. Accepted: the error is why the run failed, the audit is what it found,
  and every surface reads the audit the same way whatever the outcome.
- **[A runner killed mid-write]** → A file it was writing is counted as added or modified like any other; the audit
  reports what's in the workspace, which is what a reviewer accepts or discards.

## Migration Plan

One pull request. Earlier ends have no `outcome.audit` and still validate and display. No spec is added or removed,
and no Purpose changes, so no infrastructure pull request is needed.
