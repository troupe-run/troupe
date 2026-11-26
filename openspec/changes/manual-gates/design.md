# Design

## Context

See proposal.md for why, and troupe-run/troupe#62 for the owner's decisions 1 to 9.

The pieces a gate builds on are already in place:

- **The run's end.** A worktree run ends in `core/runs/perform.py`, which captures the diff
  (`core/workspaces.capture`) and records `Run.Ended` through the run's agent identity.
- **Settling.** `core/runs/changes.py` keeps or drops the changes. `_accept` checks inside the settle lock
  (`.troupe/local/runs/<id>/settle`), runs `vcs.check_apply`, then `vcs.apply`, records `Run.ChangesAccepted`, and
  removes the worktree. `_discard` removes the worktree and records `Run.ChangesDiscarded`.
- **Event order.** `core/runs/aggregate.py` holds the run's event order. After the end, only settling is allowed.
- **Lineage.** It already carries `approvals: [{actor, role, at}]`, which is always empty so far. Its actor kinds are
  `human`, `agent` and `unknown`.
- **Recording a value's source.** `on_context_full` shows how a run's start records a value with where it came from:
  `{value, source}`, resolved in `perform._from_config`.

## Goals / Non-Goals

**Goals:**

- One gate module that both `perform` (troupe's step) and the new approve and reject commands use. There's one
  answer path, and it's the same as accept's.
- No window in which a run that must wait for a person can be settled without one.
- Each name that later work widens is kept in one place: the role names, the default list, and the rules for a list.

**Non-Goals:**

- Roles config, or any role besides `troupe` and `director`. Notifications. Escalations' own research and brief.
- Re-running a gate. A gate runs once, at the run's end.

## Decisions

### D1. Events: the acceptance carries the approval, and three new run events

- **Keeping the work** at a gate records the existing `Run.ChangesAccepted`, with `approvals` filled in. The
  approval belongs in the lineage of the event that keeps the work, which is what the docs and the lineage schema
  have said since the start.
- **`Run.GatePassed`** records `{from, to, reason: "conflict", files}`. `from` and `to` are role names. `reason` is a
  closed set with one value for now.
- **`Run.CueRaised`** records `{role, brief}`. The brief is `{actor, outcome, diff, added, modified, deleted,
  after?}`, where `after` is the pass that led here (`{from, reason, files}`), and is absent when the role was first
  in the list. The brief is copied rather than derived, so that a cue makes sense on its own when it travels:
  notifications and other installs (#12) will read it without the run's other events.
- **`Run.ChangesRejected`** records `{role}`, with the reason in its lineage.
- **Rejected:** a separate `Run.Approved` event before the acceptance. It's two events for one decision, and a crash
  between them would leave an approval nobody acted on.
- **Rejected:** recording a rejection as `Run.ChangesDiscarded`. A discard says nothing about a gate, and `status`
  has to tell "a person rejected it" from "someone threw it away".

### D2. The system actor

- troupe's own steps record the actor `{kind: "system", id: "core@<host>"}`. #15 decided the id: it names the
  component (the core, which the CLI runs in process until the house) and its instance (the host name, read through
  the platform seam).
- A system actor has no `source`, because no identity source resolved it, and lineage refuses one that has.
- `via` is `cli`, the surface the command came through. The cause is an event cause naming the run's `Run.Ended`,
  with the end's change id: the gate is a reaction to the end.
- The identity port is untouched. A system actor is never resolved from a source; the core builds it, like the agent
  actor `perform` builds today (`source="troupe"`).
- `core/identity.py`'s `Kind` and the client protocol's `ActorData` gain `system`, so status and logs can show who
  approved.

### D3. Where the gate runs, and the crash windows

A new module, `core/runs/gate.py`, holds the gate. `perform` calls it with the run's end. `approve` and `reject` call
it with a person's answer. Accept's apply-and-record steps are factored out of `changes._accept` so the gate and
accept share them, under the same settle lock.

- **A person first** (`[director]`): `Run.CueRaised` is recorded in the same batch as `Run.Ended`. No file work is
  needed to decide it, so there's no window where `perform` stops after the end and leaves the run unasked. That's
  the gates spec's "A cue first in the list".
- **troupe first:** after the end, under the settle lock, `check_apply` runs. If the diff applies, troupe applies it
  and records the acceptance with its approval. If it doesn't, the pass and the cue are recorded in one batch.
- **The remaining window:** `perform` can stop after the end and before troupe's step. The run is then `pending` with
  no cue. A person can settle it with accept or discard, which is all troupe would have done short of raising a cue.
  Nothing a person had to approve gets through, because a list that starts with a person never has this window.
  This is recorded as a risk, and a test pins it.

### D4. Event order

The aggregate's order after the end becomes:

1. at most one `Run.GatePassed`, from `troupe`, before any cue;
2. at most one `Run.CueRaised`;
3. one settling event.

While a cue is open, the only settling events allowed are an acceptance with an approval in the cue's role, and
`Run.ChangesRejected`. `Run.ChangesRejected` needs an open cue. A `Run.ChangesDiscarded`, or an acceptance with no
approval, is refused while a cue is open, with `run.waiting-at-gate`. That backstops the handler check, as
`_can_settle` does for `run.changes-settled`. Recording anything out of this order is `run.out-of-sequence`, as today.

### D5. The approvers' rules live in one place

- `core/gates.py` holds the role names (`troupe`, `director`), the default list, and `approvers_problems(list,
  workspace)`.
- Config's actor check (`core/config/kinds.py`) calls it for each actor. So the rules apply to `config set`, to a
  hand edit's sweep, and to a merged config, all through `kinds.problems`. `core/config/merge.py` is untouched.
- The actor schema types `approvers` as an array of `enum: ["troupe", "director"]` with `minItems: 1`, so editors
  complete it. The order, ending in a person, no duplicates, and the workspace rule are in `approvers_problems`. Each
  is a `config.invalid` problem naming the path and the fix.
- Roles config later widens the names. The schema becomes a role-name pattern, and the check looks the name up in
  roles.
- A run's start records `approvers: {value, source}` (snake_case in the payload, like `on_context_full`), resolved
  in `perform._from_config` from the actor, or the default. A run whose workspace is `theatre` records no approvers.

### D6. What the client protocol and the projections show

- **The changes state** gains `waiting` and `rejected`:
  - `waiting` has `diff`, `worktree` and `cue` (`{role, raisedAt}`);
  - `rejected` is a settled state (it needs `settledAt` and forbids `worktree`).
  - `run.changes-settled`'s `details.settled` gains `rejected`.
- **The run summary** gains:
  - `approvers` (`{value, source}`), on worktree runs;
  - `gate`, the ordered steps. A step is `{step: "passed" | "cue" | "approved" | "rejected", role, at, ...}`, and an
    answer names its actor and reason.
- **The status result** gains `cues`: every open cue in the theatre, whatever the limit, newest first.
- **The logs result** gains gate entries after the run's events and notices. Following stops at the end as today, so
  `logs --follow` doesn't wait for a person.
- **New methods** `approve` and `reject`. Their requests mirror accept's and discard's (`run`, `reason`,
  `rehearse`), and so do their results: the files kept, or the worktree removed.

### D7. Error codes and the exit code

- **New error codes:**
  - `run.waiting-at-gate`: accept or discard while a cue is open. Its details are the role, the run, and the command
    that answers it.
  - `gate.no-cue`: approve or reject with no open cue. Its details are the changes' state.
  - `gate.not-a-holder`: an `agent` identity answering. Its details are the role.

  All of them are `FAILURE`, and they're catalogued in `errors.py`, `error.schema.json` and `contributing/runs.md`. Each
  has a test that raises it.
- **`ExitCode.WAITING = 4`:** `perform` returns it when the run succeeded and its work waits at a gate. A script can
  tell kept (0) from waiting (4) without reading output. Standard output still says `run <id> succeeded`.
- **Rejected:** exiting 0 for both. A script chaining `perform && next` would carry on while the work isn't kept.

### D8. Who may answer

- `approve` and `reject` resolve the identity as every command does, then refuse an `agent` kind with
  `gate.not-a-holder`.
- Any `human` identity holds `director` (decision 1). The approval records that raw identity, with role `director`.
  Mapping identities to people is #44's.

## Risks / Trade-offs

- **[Risk] troupe applies a run's changes onto a working tree the person has edited since the run started, mixing in
  with their own uncommitted work.** → It applies only when every hunk applies cleanly, unstaged, as accept does
  today. The run's start already warns with `workspace.uncommitted-unseen`. An actor that must never land
  unreviewed sets `[director]`.
- **[Risk] A `perform` that stops between the end and troupe's step leaves a `pending` run with no cue** (D3). → Only
  a list that starts with `troupe` has this window, and troupe would have kept the work anyway. A test pins that
  accept settles it, and that a `[director]` run never reaches `pending`.
- **[Trade-off] The default changes 0.1.0's behaviour: work now lands without asking.** → This is the owner's
  decision 4. The audition sets `[director]`, so a first run still asks, and the first-run docs say what the default
  does.
- **[Risk] A cue answered on two clones, merged, gives two settling events.** → The store's fork rules apply, as for
  two accepts on two clones today. Cross-install answers are #12's.

## Migration Plan

troupe is pre-1.0 and no recorded runs need keeping (no compatibility leniency before 1.0). `Run.Started` requires
`approvers` on worktree runs from this change on, and there is no "recorded before" form. Rollback is reverting the
change.

## Open Questions

None that change the specs or tasks. The wording of the status and perform lines is settled in the CLI's renderers
against the spec's scenarios.
