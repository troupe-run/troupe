# Design

## Context

See proposal.md for why. After `performances` (#545), these parts of the code shape this change:

- **Config kinds.** Config has two kinds, `actors` and `runtimes` (`troupe.core.config.kinds`). Each has a JSON
  Schema in `protocol/schemas/config/`, pydantic models generated from it (`scripts/generate_models.py`), cross-kind
  rules checked whole (an actor naming a runtime that exists), a projection to `.troupe/<kind>/<name>.yaml`, and
  renames (`config mv`). A runtime's rename carries the actors that name it.
- **perform is one run.** `troupe.core.runs.perform.perform()` refuses what it can, syncs config, then records one
  performance and one run.
  - The run happens in a worktree made at HEAD (`workspaces.plan_worktree`, `make_worktree`).
  - It's captured against the commit (`workspaces.capture`, `vcs.capture(path, baseline, …)` with the base commit as
    the baseline).
  - The gate comes last: a cue with the end, or troupe's turn (`gate.troupes_step`).
- **Settling.** `troupe.core.runs.changes` handles `keep`, accept, discard and `record_settling`, and
  `troupe.core.runs.gate` handles approve and reject. Every one acts on one run. `queries.resolve` maps a reference to
  one run id.
- **Status** returns a list of run summaries. Since #545 each summary names its performance and step.
- **Config at a version.** Config has no read at a past version. A run's start records the config heads it used.

## Goals / Non-Goals

**Goals:**

- A flow runs start to finish unattended with the default approvers, and lands its work in one all-or-nothing apply.
- One driver runs every performance: an actor's is a flow of one step. There's no second path for single runs.
- What each step saw and was told is recoverable from the record: its direction by reference, and its base and
  baseline in its run's start.

**Non-Goals:**

- Fork and join, loops and swarms (#145 to #147), retrying a step, and resuming from a step.
- Notes and structured outputs between steps beyond the brief.
- Supervision beyond the terminal (#63).

## Decisions

### D1. The `flows` kind follows the runtime's pattern

- **Schema:** `protocol/schemas/config/flow.schema.json` describes `{steps: [{actor, direction?, approvers?}]}`, with
  `steps` at least one item and `approvers` referring to the actor schema's definition. Models are generated as for
  the other kinds.
- **The kind:** `kinds.py` gains `FLOWS`, and its cross-kind rules join the actor-runtime ones:
  - a step naming a missing actor;
  - a step naming an actor that works in the theatre;
  - a flow named like an actor.

  Each is a `Problem` whose `related` paths include the actor, so a merge that breaks one is a conflict on both
  sides.
- **Projection:** a flow is written to `.troupe/flows/<name>.yaml` like a runtime file, and hand edits and hand moves
  are swept the same way.
- **Renames:** `config mv` accepts `flows.<name>`. An actor's rename carries the flow steps that name it, as a
  runtime's rename carries actors.

Alternatives:

- **Steps on an actor.** Rejected by decision 1.
- **One `flows.yaml` holding every flow.** Rejected: every other kind is one file per entity, so diffs and hand edits
  read the same way.

### D2. One driver runs every performance

`perform()` resolves its name to a **plan**: for an actor, one step; for a flow, its steps. Each step holds its
`_What` (the actor as config defines it), the step's direction and its resolved approvers with their source (`step`,
`actor` or `default`). Every check that can refuse runs over every step before anything is recorded:

- policy and stage;
- the runner installed;
- the runtime and its credential;
- the theatre's HEAD.

The driver then runs steps from a given index. A step is today's single-run body, moved into `_run_step`:

1. the run's lease;
2. its start (in the performance's start batch for step 1);
3. its worktree;
4. the runner;
5. its end;
6. its gate.

After each step, the driver goes on, or stops at a waiting gate or a failure.

`approve` calls the same driver from the next step (D7). Each run keeps its own lease, so a performance's state is
its current run's.

### D3. A step's worktree is the base commit plus the work so far

Every step works from the **performance's base**: the HEAD commit when the performance started, which step 1's run
start records. Step k's worktree is built in three moves:

1. It's made at that base, as today.
2. The performance's diff so far (D4) is applied inside it, all or nothing: new VCS port method
   `apply_in_worktree(path, diff) -> baseline`. The git adapter runs `git apply` in the worktree and returns the
   index's `write-tree`.
3. The worktree's `baseline` is set to that tree.

`capture` already diffs against the worktree's baseline, so the step's diff and its audit cover only the step's own
changes. The run start's workspace records the base and, for step 2 onward, `builtOn`: the run of the step before.

An apply that fails ends the step `could-not-start`, with the error, and the performance `failed`. That shouldn't
happen, since the diff was captured from the same base.

Alternative: **commit each step in the worktree, and start the next from that commit.** Rejected: it writes commits
into the person's repository, which are shared with every worktree, and #153 keeps "committed" for later.

### D4. Each step's end records the performance's diff so far

A worktree run that's a step of a flow captures twice:

- its own diff, against its baseline, as `changes.diff`;
- the performance's diff so far, against the performance's base, as a new `changes.sofar` artifact reference.

`sofar` is left out of a one-step performance's run, since it would equal `diff`.

The last step's gate, `troupe diff <performance>`, and accepting a stopped performance all apply or show the latest
`sofar`. Nothing has to replay diffs in order.

### D5. Gates between steps

- **Approvers:** a step's are resolved by D2 and recorded with their source.
- **A step before the last, with changes:**
  - With troupe first, troupe records `Run.ChangesApproved` straight away. The step's work applies to the work so
    far by construction, so there's nothing to check.
  - With a person first, the cue is raised with the end, as today.
  - `Run.ChangesApproved` settles the run's changes as `approved`. The step's worktree is removed once the next
    step's worktree is made, since its work lives on in the next.
- **The last step:** it reaches its gate when the performance has changes: the step's diff, or `sofar` when the
  performance has more than one step. Keeping applies `sofar`, or `diff` for one step, through `changes.keep`.
- **Lineage:** `Run.ChangesApproved` carries the approval. Lineage's approval rule and the record-time check widen to
  "the event that lets the work through" (`Run.ChangesAccepted` at a gate, or `Run.ChangesApproved`).

### D6. The brief, and the history files

- **The brief:** the step's direction is assembled by one function, from:
  1. the performance's direction;
  2. the step's own direction;
  3. the previous step's brief;
  4. one line per earlier step.

  The previous step's brief comes from its run view: its actor, its outcome, the files its diff names (parsed from
  the diff's `diff --git` headers) and the final message of its result event. It's stored as an artifact by
  reference, as every direction is, so the run start records exactly what the step was told.
- **History files:** before the runner starts, the driver writes `.troupe/performance/<n>-<actor>/` into the step's
  worktree for every earlier step:
  - `brief.md`;
  - `changes.diff`, the step's own diff from the artifact store;
  - `log.md`, a plain rendering of the run's events and notices, produced in core. The CLI's renderer can't be
    imported from core, and the masking is already applied to what was recorded.

  `.troupe/` is never part of a diff, and every runner already refuses to change anything under it.

### D7. Approve carries the flow on

`approve` on a cue at a step before the last records `Run.ChangesApproved` with the person's approval, then calls
the driver from the next step:

- Config is as at the performance's start: `config_at(store, heads)` merges the config history up to the recorded
  heads, the same merge config uses, cut at those heads.
- The command streams perform's updates.
- Its result is a perform result.
- The CLI renders it as `perform` does, with the same exit codes.

At the last step, approve keeps the work as today. `--rehearse` runs every check over the remaining steps and stops.

### D8. A stopped performance is settled whole

`reject` ends the performance `rejected` and removes every worktree it still has: the waiting step's, since earlier
ones were removed as D5 says.

For a performance of more than one step, a failure, a cancel or a perform that stopped leaves the last run's worktree
and its `sofar`:

- `accept <performance>` applies `sofar` (or the failed step's `diff`, when it's step 1).
- `discard <performance>` removes the worktree.
- Both are recorded on the last run, and end the performance if it's open (as #545 built).
- Naming any run of such a performance in `accept` or `discard` is refused with `performance.settled-whole`, naming
  the performance.

### D9. A reference resolves to a run or a performance

`resolve` returns what a reference names, a run or a performance, and each command chooses:

- `approve` and `reject`: the performance's waiting step, else `gate.no-cue`;
- `accept`, `discard` and `diff`: the performance as a whole;
- `status` and `logs`: the performance with every step.

`performance.several-runs` has no use left, and is removed from the catalogue.

### D10. Status and logs read performances

- **Status:** `StatusResult` lists **performance summaries**. Each holds:
  - its id;
  - what was performed;
  - the number of steps;
  - its state: `running`, `waiting`, `ended`, `interrupted` or `unfinished-elsewhere`, worked out from its end and
    its current run;
  - its outcome and the step it's at;
  - its runs' summaries.

  A one-step performance's line is unchanged. A flow's line reads like `01JD6…  review  waiting at step 1/2`, with
  its runs indented under it. Open cues stay listed above.
- **Logs:** `troupe logs <performance>` returns every step's log in order, each entry naming its run. `--follow`
  follows step after step until the performance ends or stops.

### D11. Protocol

Every change below lands in the commits whose code needs it, marked breaking:

- `config/flow.schema.json`;
- `events/run-changes-approved.schema.json`;
- `performance-started`'s `performed.kind` gains `flow`, and its steps drop `maxItems`;
- the approvers' `source` gains `step`, in the event, client and config schemas;
- `run-ended`'s changes gain `sofar`, and a run start's workspace gains `builtOn`;
- the client's status result, performance summary, logs result and approve result and updates;
- the error catalogue: `performance.settled-whole` added, `performance.several-runs` removed.

## Risks / Trade-offs

- **The change is large** (config, VCS, the driver, settling, reading back, docs). → Six task groups, each its own
  reviewable push on one pull request, in dependency order. The orchestrator is told before any split.
- **Moving perform's body into a step function can change single-run behaviour.** → Every existing perform test
  stays as it is and must pass unchanged after group 3. A one-step performance is the regression oracle (see the
  differential-test rule).
- **A history file could leak a credential.** → `log.md` is rendered from recorded events, which perform masks before
  recording. A test runs a runtime with a credential through two steps and checks it's in no history file.
- **`apply_in_worktree` on Windows** (CRLF, file modes). → It uses the same `git apply` options as `apply`, with tests
  on all three platforms.

## Migration Plan

None for data: older runs are already refused (#545). The protocol release is breaking. After the merge,
troupe-run/infrastructure records the `flows` spec's Purpose, and updates `cap:config`'s description to name flows.
