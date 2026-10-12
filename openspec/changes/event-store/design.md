# Design

## Context

See proposal.md for why. The repository has the CLI skeleton, `troupe.core` (errors, exit codes, defaults, file
helpers) and the `platform` seam (atomic replace, directory locks, friendly paths). It has no events, no adapters
and no theatre layout.

The constraints that shape this design come from #1 and its 2026-10-12 comment, #9, #35, the bootstrap design (D1:
first-party adapters are their own packages; D6: locks are a lock file in the protected directory), and the project
context (text state, lineage on every event, adapters for VCS, storage and identity, OS behaviour behind
`platform`, refuse rather than guess).

**Prior art.** cladus (`~/Projects/hps.gd/cladus.ai`, `spikes/jsonl-recorder` and `packages/cladus/src/cladus/journal`)
is the prototype #1 describes. It passes the library's recorder suite unmodified (48 tests). Its findings are
reused here, and its weak points are fixed as #1 directs:

| cladus | Finding or weak point | Here |
|---|---|---|
| A file per insert | 93× the cost of batching, and the file count grows without limit | One segment per session per branch (D4) |
| The hash covers wall time and actor | Two clones never agree on an ID | The hash leaves out all lineage (D3) |
| Per-branch order logs in git | Conflicts with "never rewrite git"; dead branches' logs pile up | The order log is local and gitignored (D5) |
| A forked stream is refused, with no way out | Divergence can't be settled | A settling event (D6) |
| An absent parent is admitted, and read as concurrent (cladus 0021) | #1 decides the opposite | Refused, naming the file and the fix (D7) |
| Merge is replay into a per-branch log (0015); a crash between the two writes self-heals into replay | Kept | D5 |
| Subscription reuses `ListenNotifySubscription`; only `listen`/`unlisten` are owed (0014) | Kept | D10 |
| Tracking can't be atomic with events in a file store, so delivery is at-least-once | Kept | D5 |
| Session IDs must be monotonic within a process, or same-millisecond files sort wrongly | Kept | D4 |
| `pycryptodome` is a test dependency of the library's suite | Kept | Tasks |
| A single writer per journal is assumed (one daemon) | troupe has no daemon yet, and CLI commands run concurrently | A cross-process write lock (D10) |

## Goals / Non-Goals

**Goals:**
- The library's recorder suite passes unmodified on Linux, macOS and Windows.
- Every rule in #1's agreed direction and its 2026-10-12 comment has a test that fails when the rule breaks.
- #33 change C can record runs and build `status` and `logs` projections without changing the event format.

**Non-Goals:**
- Performance beyond what the suite measures and the skeleton needs. A cold-load number is recorded (tasks), not
  optimised.
- Two theatres sharing one event directory, or a theatre on a network share (already unsupported by `platform`).
- Mapping identities to people and roles (#9 question 3).

## Decisions

### D1. Packages and ports

| Distribution | Holds | Imports |
|---|---|---|
| `troupe` | `troupe.core.events` (the event-store service, record and lineage types, the settling event base), `troupe.core.identity` (the chain and the source port), `troupe.core.vcs` (the port), notices, errors, defaults. It uses the runner contract's `troupe.platform.processes` (D11) | `eventsourcing` |
| `troupe-store-text` | `troupe_store_text`: the recorders and the `InfrastructureFactory` (an `eventsourcing` persistence module) | `troupe.core`, `troupe.platform`, `eventsourcing` |
| `troupe-vcs-git` | `troupe_vcs_git`: the git adapter | `troupe.core`, `troupe.platform` |
| `troupe-vcs-files` | `troupe_vcs_files`: the plain filesystem adapter | `troupe.core` |
| `troupe-identity-local` | `troupe_identity_local`: the `env`, `vcs` and `os-login` sources | `troupe.core` |

- **Adapters are found by name through entry points** (`troupe.store`, `troupe.vcs`, `troupe.identity`).
  `troupe.core` never imports an adapter package. An import-linter contract enforces that, so every port is
  proven by a separately packaged implementation (bootstrap D1). Decision #37 confirms it: bundled first-party
  adapters run in process, through the direct transport, loaded by entry point (D13).
- The workspace's dev group installs all of them. Which adapters a released `troupe` depends on is release
  packaging, which is out of scope.
- **The service, not the recorder, enforces lineage.** The library's suite records payloads such as `b"state1"`
  and `b"{}"`, so the recorder must accept events without lineage. Every write troupe makes goes through
  `troupe.core.events`, which validates lineage before calling the recorder. An import-linter contract keeps
  `troupe.cli` (and later surfaces) from importing a recorder directly.

Alternatives considered:
- Adapters as subpackages of `troupe`. Simpler, but it contradicts bootstrap D1, and the ports would never be proven
  from outside.
- The `troupe` distribution depending on its adapters. That makes a dependency cycle between distributions.

### D2. Theatre layout

```
.troupe/
  .gitignore         "local/". Written only if missing; never rewritten.
  .gitattributes     "events/** -text". Written only if missing.
  events/            tracked: <session-id>.jsonl segments
  local/             gitignored
    .lock            the store's write lock (platform D6)
    order/<branch-key>.jsonl
    tracking/<branch-key>.jsonl
    artifacts/       runner-contract's LocalArtifactStore (#34): transcripts and large payloads by hash
```

- The lock lives in `local/`, not `events/`, so it is never a tracked file.
- Anything else the library asks a store for (such as its snapshots, `purpose="snapshots"`) is derived, so it lives
  under `local/purposes/<purpose>/` and is never committed.
- `local/artifacts/` belongs to the runner contract's artifact store. It's listed here because this change writes
  the `.gitignore` that covers it (`local/`).
- `-text` stops git (`core.autocrlf` on Windows) from rewriting line endings in event files. The reader still
  accepts `\r\n`, in case a file was checked out before the attribute existed.
- A branch key is the branch name made filename-safe on every platform, plus a short hash of the exact name, so
  `a/b` and `a-b` never share a file. A detached HEAD uses `detached`. The filesystem adapter uses `default`.
- The store creates directories and files only when it first records an event. Reads create nothing.

### D3. Records and content hashes

Each segment starts with a header line, followed by one line per event:

```json
{"format":1,"segment":{"session":"01K7…","vcs":"git","branch":"main"}}
{"format":1,"id":"sha256:9f2c…","stream":"6c1e…","stream_type":"uuid","version":3,"topic":"troupe.core.runs:Run.Started","parents":["sha256:41ab…"],"state":{"lineage":{…},"run":"…","timestamp":"…"},"batch":{"id":"01K7…","index":0,"size":2}}
```

- **Payload inline when exact.** `state` is written as a JSON object only when re-encoding it canonically
  reproduces the stored bytes exactly. Otherwise it is written as `state_b64`. troupe's own transcoder emits
  canonical JSON (sorted keys, compact, UTF-8, `allow_nan=False`), so troupe's events are always readable inline.
  Encrypted or compressed state, and the suite's `b"state1"`, round-trip byte for byte. This fixes cladus, which
  re-encoded loosely and relied on its test payloads happening to survive.
- **The ID** is `sha256:` plus the hex digest of the canonical JSON of `{stream, stream_type, version, topic,
  parents (sorted), state}`, where `state` leaves out the top-level `timestamp` and `lineage` keys when it is a
  JSON object, and is the base64 bytes otherwise.
- **The hash leaves out all lineage, not only wall time and actor.** #35 names wall time and actor. But branch,
  HEAD, via, reason and change ID differ between clones too, and including any of them would defeat "two clones
  that make the same change agree". Lineage still records them. When a merge brings the same ID from two
  recordings, the store keeps both lines (it rewrites nothing). Reads return the event once (the first recording
  in replay order), and `recordings(id)` returns every recording's lineage. Nothing is lost.
- **Equal IDs are not integrity errors.** The library's integrity error is about a stream and version recorded in
  this branch's history. An equal ID arriving by merge is the same event. An equal ID recorded locally is still an
  integrity error, because its stream and version are taken.
- **Strict reading.** Every JSONL line troupe reads (segments, the order log and tracking, D5) is parsed with
  duplicate keys refused (`object_pairs_hook`) and non-finite numbers refused (`parse_constant` for `NaN`,
  `Infinity` and `-Infinity`). Either one fails with `events.malformed-record`, naming the file and the line. The
  plain reader would keep the last duplicate and accept `NaN` silently, which is the quiet fall-through D9 rules
  out. The writer already refuses both (`allow_nan=False`, built from dicts). The allowances for a torn last line
  (D4, D5) are for incomplete writes only. A complete line that is malformed is always an error.
- **The id is checked on read.** Each line's `id` is recomputed from its content, and a mismatch (a line edited by
  hand) is `events.malformed-record`.
- `format` is checked on every line. An unknown format fails with `events.unknown-format`, naming the file, the
  line, and the fix (upgrade troupe).

Alternatives considered: BLAKE2b like cladus. SHA-256 is chosen because it is what other tools, and the runner
contract's transcript references, will most likely use (D-Runner).

### D4. Segments and sessions

- **A session is one opened store in one process.** Its ID is a ULID that is monotonic within the process. The
  segment `events/<session-id>.jsonl` is created with its header on the session's first batch.
- **One branch per segment.** Before each batch, the session checks whether the branch changed. If it did, the session
  starts a new segment with a new ULID. This is "one segment per session per branch".
- **That check is cheap.** A run streams hundreds of batches, and a git call per batch would dominate. So the VCS
  port has `branch_token()`, which is a cheap value that changes whenever the branch might have. For git, the
  adapter asks once for the paths of HEAD, the index and the HEAD reflog (`git rev-parse --git-path`, which handles
  worktrees), and the token is their sizes, mtimes and inodes. HEAD moves on a switch; the index changes on add,
  commit, switch, merge and reset; the reflog grows whenever HEAD moves. So the token changes whenever the branch,
  HEAD or what is committed might have, which is everything visibility (D7) depends on. The session asks for the branch again only when the token
  changes. The filesystem adapter's token never changes.
- **A batch is one write.** Every line of the batch is appended through one handle, then fsynced, by
  `append_bytes` in `troupe.platform.files`: in binary mode, so Windows never turns line feeds into CRLF, and with
  the directory fsynced when the segment is new (POSIX). Each line carries `batch: {id, index, size}`.
- **An incomplete batch.** A crash can leave a segment ending in a partial line or a short batch. That batch's
  `insert_events` never returned, so it never took effect. Reads leave out an incomplete batch *at the end of a
  segment* and report `events.incomplete-batch` (the file, and the fix: remove the trailing lines, which never
  took effect). Anything malformed elsewhere fails with `events.malformed-record`. The store never truncates a
  file itself, because the file may be committed, and troupe never rewrites what the user didn't ask to change.
- **File count.** Each CLI command that records is a session, so a theatre gains one segment per recording
  command. That is much fewer files than cladus's one per insert, but it still grows. A long-lived session (the
  house, #5) cuts it further. A cold-load time for 10,000 segments is measured and recorded in
  `docs/event-store.md` (tasks), so this is judged on a number.

Alternatives considered:
- Appending to one tracked file per branch. Rejected in #1: two clones on one branch conflict.
- One file per batch (cladus). The file count grows without limit.

### D5. Local ordering, replay and tracking

- **The order log** (`local/order/<branch-key>.jsonl`) starts with `{"epoch": "<uuid>"}`. Each later line is
  `{"n": <id>, "event": "<hash>"}`. IDs are dense from 1, appended, and never rewritten. This is exactly the shape
  the library's suite expects (cladus 0015).
- **On open, and before every write and read under the lock**, the store scans `events/` for new or grown segments
  (it reads only the bytes it hasn't seen), and works out which events are visible (D7). Visible events that are
  missing from the order log are replayed: appended in topological order by parents, then by segment session ID,
  then by line. Within one session that keeps the order the writer used, so causality across streams holds there
  too. A merge, a pull, and the crash window between writing a segment and appending to the order log all take
  this one path.
- **Rebuild.** If the order log names an event that is no longer visible (its file was removed, or a reset dropped
  it), the store writes a new order log with a new epoch from the visible events, and reports
  `events.order-rebuilt` with the reason. That loses nothing, because the order is derived. It's the
  "works things out locally" rule from #1.
- **Tracking** (`local/tracking/<branch-key>.jsonl`): `{"epoch", "application_name", "notification_id"}` lines.
  `max_tracking_id` ignores lines from an earlier epoch, so after a rebuild every follower starts again from 0 and
  its projection is rebuilt. Delivery is at-least-once (cladus): a deterministic policy that reprocesses produces
  the same events, which are refused as duplicates. A torn last line (an interrupted append) is trimmed from the file, because troupe alone writes it and that line
  never took effect; otherwise the next append would land after it. Damage anywhere else fails.
- **Per branch:** switching branches switches the order and tracking files, so each branch's IDs stay stable for
  that branch.

Alternatives considered:
- An order log in git (the prior art). It conflicts with "never rewrite git" and leaves dead branches' logs
  behind. Rejected in #1.
- IDs derived from position at load time. A merge silently re-delivers some events and skips others (cladus 0013).
  Rejected.

### D6. Forks and settling

- **Parents.** A new event's parents are its stream's current visible head. A stream's first event has none.
  Inside a batch, each event's parent is the one before it.
- **Detection.** A stream has more than one head when two visible events share a parent (or both have none) and
  neither descends from the other. That's what a merge of two branches that both appended to the stream produces.
  `select_events` on such a stream raises `events.stream-forked`, naming the stream, each head's ID, version and
  file, and the fix (settle it). `insert_events` to it raises the same error. `forks()` lists every forked stream
  without loading any, so a report can always be produced (cladus 0022).
- **Settling.** `troupe.core.events.settle(stream, parents, state, lineage)` records a settling event:
  - its parents are every current head, and anything less fails with `events.settle-incomplete`, naming the
    missing head;
  - its version is the highest head version plus 1;
  - its type is a subclass of troupe's settling-event base, which follows the library's `Snapshot` mechanics: its
    `mutate(None)` builds the aggregate from the state it carries.
- **Loading a settled stream** reads from the latest settling event on the head's path, then forward. The library
  applies each event's `mutate`, starting from `None`, so the settling event builds the state, and no event from
  either branch before it is applied. `history(stream)` returns every event, topologically, for history reads.
- **What decides the settled state** is the aggregate's business. Config's semantic three-way merge arrives with
  config. This change proves the mechanism with a test aggregate.

Alternatives considered:
- Following the longest branch, or the highest version, as the main line. That rewards whoever recorded more, and
  invents a winner (cladus 0022's rejected options).
- Replaying both branches in `(version, hash)` order. That's last-writer-wins with a tie-break.

### D7. Visibility, abandoned edits and missing parents

- **Committed vs uncommitted.** A segment is *committed* when the VCS adapter reports its path as in HEAD or the
  index. A staged file no longer travels with `git switch` the same way, and it's in the user's hands.
- **Other branches.** An uncommitted segment whose header names a branch other than the current one is left out of
  every read and every uniqueness check, and reported as `events.other-branch` (the segment, its branch, and the
  fix: switch back to that branch and commit the events, or delete the file if they're not wanted). Committed
  segments are always visible, whatever branch made them, because a merge put them there.
- **No classifying** (#1, 2026-10-12). Nothing is classified as abandoned or stashed. An edit and its revert are
  both events. The store's part of that rule is to keep every visible event and never drop or hide one for being
  "undone".
- **The sweep that records a revert** (for example, `git checkout -- actors/tester.yaml` putting 3 back after troupe
  recorded 5) belongs to whatever owns the file: config (#6, #7). That sweep records an ordinary hand-edit event,
  with lineage `via: file`, actor `{kind: unknown}` and the file's before and after hashes. This change provides
  that lineage shape and its tests. It doesn't build the sweep, because the skeleton has no hand-editable file.
- **Missing parent.** An event whose parent isn't visible makes reads of its stream fail with
  `events.missing-parent`. The error names the dependent event's file and line, the missing parent's ID, and the
  fix: restore the removed file, or remove the dependent file too. This replaces cladus 0021's "admit", as #1
  decides. A parent that is only in an other-branch segment is missing too, and the error also names that segment.
- **Keep-and-ask later.** Every event's lineage already has the branch, HEAD and the source file's before and after
  hashes, so a later "this edit was abandoned: keep or drop?" prompt needs no format change.

### D8. Lineage

`protocol/schemas/lineage.schema.json`, closed (`additionalProperties: false`):

| Field | Shape |
|---|---|
| `actor` | `{kind: "human"\|"agent", id: string (min length 1), source: string}` or `{kind: "unknown"}` |
| `via` | `"cli"`, `"file"`, `"runner"` or `"server"` |
| `at` | RFC 3339, UTC, `Z`, milliseconds |
| `reason` | string or `null` |
| `change` | ULID: the correlation ID shared by every event that follows from one command |
| `cause` | `{kind: "command", id: <change ULID>}` or `{kind: "event", id: "sha256:…"}` |
| `approvals` | array of `{actor, role, at}` (empty until gates exist) |
| `vcs` | `{adapter, branch: string\|null, head: string\|null, source: {path, before, after}\|null}`; `before`/`after` are `sha256:…` or `null` |

- Lineage travels inside the event's state (`state.lineage`), so projections read who did what straight from the
  domain events, and the library delivers it with no extra channel. The content hash leaves it out (D3).
- `source.path` is relative to the theatre, with `/`, never a host path (theatres are addressed by ID).
- The time comes from an injectable clock, so tests are deterministic.
- **Correlation and causation (owner, 2026-10-12).** `change` is the correlation ID. A command mints one, and
  every event that follows from that command carries it. `cause` says what made this event happen. It's
  `{kind: "command", id: <change>}` for an event a command recorded directly, or `{kind: "event", id: <hash>}` for
  one recorded in reaction to another event. A reaction inherits its trigger's `change` and never mints one. So if
  command C records E1, and E2, E3 and E4 react to E1, all four share C's `change`, and E2 to E4 name E1 as their
  cause.
  - The service checks both at write time. A command cause's ID must equal `change`. An event cause must name an
    event visible on this branch (`events.cause-unknown`).
  - `record_reaction(trigger, events, …)` derives `change` and `cause` from the trigger, so a follower can't get
    them wrong. Policies and projections that record go through it.
  - The settling event (D6) and the hand-edit sweep's events (D7) have a command cause.
  - `cause` is lineage, so it stays out of the content hash (D3). Two clones that react identically to the same
    event still agree on the reaction's ID.
  - A cause is checked only at write time. If the cause's file is later removed by hand, the reaction still reads.
    History shows the cause as not present. It's a statement about origin, not a structural parent like `parents`
    (D7), so a missing cause doesn't block reads.
- Python types mirror the schema, and a test validates every built shape against it (protocol README).

### D9. Identity: the default chain (#9, agreed by the owner 2026-10-12)

**Decision: `env` (`TROUPE_ACTOR`) → `vcs` (git `user.email` for the theatre) → `os-login` → refuse.** This is #9's
own proposal, agreed as proposed.

**Absent passes on; malformed or ambiguous fails (owner, 2026-10-12, a general safety rule).** A source that finds
nothing passes to the next source. A source that finds something it can't use cleanly fails the command, naming the
source, the value and the fix. It never falls through quietly to the next source or a default, because a quiet
fall-through records the wrong person, and nothing shows it. In this chain:
- `TROUPE_ACTOR` set but not `human:<id>` or `agent:<id>` → `identity.invalid-override`.
- More than one `user.email` in the winning setting → `identity.ambiguous`, listing them. As in git, a more
  specific setting overrides a less specific one (the repository's over the global), so a global email with a
  repository email is not ambiguous; two in the same file are. The git adapter reports the winning setting's values
  (`git config --get-all --show-scope`).
- A chain naming a source that isn't installed → `identity.unknown-source`.
- `user.email` unset, or set to the empty string → absent, so it passes on. git itself treats an empty value as no
  identity. An empty `TROUPE_ACTOR` counts as unset in the same way (owner, 2026-10-12).

The rest of this change follows the same rule: an unknown record `format`, a malformed line, an unknown cause, and a
settle that names too few heads are all errors, never defaults. #35's starting default (git user, OS user, refuse) is the same chain without the override.

The questions #9 asks, answered:

1. **Order:** as above. The override comes first because an explicit statement beats an inferred one, and because
   CI, containers and test harnesses need a way to say who is acting without editing git config. The VCS identity
   comes before the OS login because it is chosen per person and is portable across machines, while the login is
   a machine account (`root` in containers, `runner` in CI).
2. **Record which source answered?** Yes: `actor.source` is `env`, `vcs` or `os-login`. A hosted source (OIDC)
   later adds its own name.
3. **Identity to person and role:** not here. Lineage records the raw ID. Roles config maps it later.
4. **`TROUPE_ACTOR`:** kept, as `human:<id>` or `agent:<id>`. A malformed value is an error
   (`identity.invalid-override`), never a fall-through: a typo must not quietly become someone else.

Mechanics:
- The chain's default is `IDENTITY_CHAIN = ("env", "vcs", "os-login")` in `troupe.core.defaults`. Sources are found
  by name through the `troupe.identity` entry point. An unknown name in the chain is an error
  (`identity.unknown-source`).
- `vcs` asks the VCS port for its configured identity, so it answers only when the adapter has one (git). It
  answers nothing for the filesystem adapter (#9: "The VCS source exists only when the VCS adapter is git").
- `os-login` uses `getpass.getuser()`, which is portable. A failure or an empty result is no answer.
- Nothing resolves: `identity.unresolved`, listing the sources tried and how to set each one. It's raised before
  any write.
- **Agents aren't resolved by the chain.** When troupe runs an actor, troupe assigns the agent identity from the
  actor's configured name (`source: "troupe"`). The runner never claims one (D-Runner).

Alternatives considered:
- `user.name` instead of `user.email`. Names collide and change. Email is the closer thing to a stable ID.
- Leaving out `TROUPE_ACTOR` (#35's wording). Then a harness has to rewrite git config to set an actor, which is
  worse.
- An `unknown` actor when nothing resolves. The constraints forbid it: fail when there's no identity.

### D10. Concurrency and subscription

- **Within a process:** a `threading.Lock` per store serialises recorder calls. It's taken *before* the directory
  lock, because the platform lock registry would otherwise raise `lock.already-held` for a second thread
  (`platform/locks.py` keys held locks by process).
- **Across processes:** each write takes `troupe.core.files.directory_lock(.troupe/local)`, which is bounded and
  announced with the existing defaults. Under it, the store rescans (D5), checks uniqueness, appends the segment
  batch (fsync), then appends the order log (fsync). Reads don't take the lock. They rescan, and tolerate a batch
  still being written by treating an incomplete trailing batch as not there yet. To tell an interrupted write from
  one in progress, a reader that finds an incomplete batch tries the lock without waiting: if it gets it, nobody is
  writing, the batch was interrupted, and `events.incomplete-batch` is reported; if not, another process is still
  writing, and nothing is reported. The lock file stays empty, as the platform's lock design requires (bootstrap
  D6).
- **Subscription** reuses `ListenNotifySubscription`. The recorder owes `listen` and `unlisten` over
  `threading.Event` (cladus 0014). Writes in this process set the events. A poll at `SUBSCRIBE_POLL_SECONDS`
  rescans for other processes' writes and sets them when anything new is visible. File watching arrives with the
  house (#5).

### D11. The platform: bounded commands and environment policies

**`troupe.platform.processes` belongs to the runner contract (#34, its D6),** and this change adds nothing of its
own to it. As committed on `runner-contract` (5b5d02f, eab458c, 46dd1b6; checked 2026-10-12):

- `start(argv, *, cwd, env, line_limit, search_path=None) -> ChildProcess`: its own process group (a kill-on-close job
  object on Windows), streams, `wait()`, `kill_tree()`. Also `resolve_command()` and `MINIMUM_ENVIRONMENT`
  (`SYSTEMROOT` on Windows). Errors: `CommandNotFoundError`, `LineTooLongError`.
- `run_to_completion(argv, *, cwd, env, timeout, max_output_bytes, announce_after, input=None, on_wait=None,
  search_path=None) -> Completed(returncode, stdout, stderr)`. It's a blocking call with no event loop, so it works
  in any context. `on_wait(command, waited)` is called once. On timeout it kills the whole tree and raises
  `ProcessTimeoutError(command, timeout, stdout, stderr)`. Over `max_output_bytes` it kills the tree and raises
  `OutputTooLargeError(command, limit)`. A missing command raises `CommandNotFoundError(command)`. **A command that
  exits while a child still holds its pipes counts as still running**, so it times out rather than returning early.
- `EnvironmentPolicy(names: frozenset, prefixes: tuple, never: frozenset, never_prefixes: tuple)`, with `.selects()`,
  `.forbids()` and `.narrow(names=None, prefixes=None, never=(), never_prefixes=())`. `narrow` keeps a subset (a
  prefix may be lengthened, never shortened) and raises `EnvironmentPolicyError(name, reason)` for anything wider.
  `build_environment(policy, *, source=None, explicit=None)` returns the platform minimum, plus what the policy
  selects from `source` (default `os.environ`), plus `explicit`. An explicit value for a forbidden name **raises**
  `EnvironmentPolicyError`, rather than being dropped. Names match case-insensitively on Windows.

The git adapter calls `run_to_completion` with `env=build_environment(GIT_ENVIRONMENT)` and passes no `explicit`
values. It runs only local commands (`rev-parse`, `symbolic-ref`, `config --get-all`, `ls-files`), none of which
contacts a remote, so git starts no credential helper or `ssh`, and nothing lingers on its pipes. The default
`GIT_TIMEOUT_SECONDS` of 10 is set for that. `troupe.core` wraps the
platform errors as `command.not-found`, `command.timeout` and `command.output-too-large`, with
`GIT_TIMEOUT_SECONDS` and `GIT_MAX_OUTPUT_BYTES` (the adapter's own named defaults).

**Policies are per adapter, not one rule (owner, 2026-10-12).** Each adapter that runs commands declares its policy
as a named default in one place, **in its own package**. `troupe.core` never imports an adapter (D1), so a
git-specific policy can't live in `troupe.core.defaults`. A caller may narrow it, never widen it. (The `settings`
capability will later let config narrow it too, under the same rule.)

| Adapter | Default policy | Why |
|---|---|---|
| `troupe_vcs_git.defaults.GIT_ENVIRONMENT` | names `HOME`, `USERPROFILE`, `APPDATA`, `XDG_CONFIG_HOME`, `PATH`, `SSH_AUTH_SOCK`; prefix `GIT_`; `never` git's repository-location variables | git finds global and XDG config through the home variables (`USERPROFILE` and `APPDATA` on Windows), credentials and SSH through `SSH_AUTH_SOCK` and the user's `GIT_*` (`GIT_SSH_COMMAND`, `GIT_ASKPASS`, `GIT_CONFIG_GLOBAL`). The exclusions stop a hook-time `GIT_DIR` or `GIT_INDEX_FILE` from pointing troupe at another repository. Anything else git turns out to need is added only when a test shows it. |
| `troupe_vcs_files` | none | It runs no commands. |

- **`never` is the list `git rev-parse --local-env-vars` prints** (`GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`,
  `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_COMMON_DIR`, `GIT_CONFIG`,
  `GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_COUNT`, `GIT_GRAFT_FILE`, `GIT_IMPLICIT_WORK_TREE`, `GIT_NO_REPLACE_OBJECTS`,
  `GIT_REPLACE_REF_BASE`, `GIT_PREFIX`, `GIT_SHALLOW_FILE`, and the rest it prints), plus `GIT_NAMESPACE` from the
  runner contract's list. It's pinned as a constant, not read at runtime, so behaviour doesn't change with the
  installed git. A test runs the installed git's command and fails if it prints a name the constant lacks, so a new
  git release can't add a leak quietly.
- **A too-tight policy fails quietly.** If git can't see `HOME`, `user.email` is unset, and identity falls through
  to the OS login. That's why the identity tests resolve `user.email` from a global config under a temporary `HOME`
  (and `XDG_CONFIG_HOME`) through the real policy.
- **Sync, in a worker thread.** The `eventsourcing` recorders are synchronous, and so is the store, including its git
  calls. An async caller (change C's `on_event`) calls the store through `asyncio.to_thread`, which also keeps
  fsyncs off the event loop. So the store never calls `run_to_completion` from a thread with a running loop, and it
  doesn't need the sync form to work inside one.

**Platform spec.** The runner contract's `platform` delta holds these requirements: an explicit environment built from
a declared policy, narrowing only, killing the whole tree, and running to completion within a bound. This change
has no `platform` delta, so the main spec holds each requirement once. `run_to_completion` is a blocking call with no
event loop of its own, so it works from any thread. The store still runs off the loop through `asyncio.to_thread`,
to keep fsyncs off it.

Alternatives considered:
- All or nothing: inherit the whole environment, or pass none. Rejected by the owner: inheriting leaks secrets into
  every child, and passing nothing breaks git's config and credentials.
- Read the exclusions from `git rev-parse --local-env-vars` at runtime. Rejected: it costs a git call for every
  command, and an older git would quietly pass newer variables.
- `GIT_ENVIRONMENT` in `troupe.core.defaults`. Rejected: core would then know about one adapter.

### D12. Notices and error codes

- `protocol/schemas/notice.schema.json` has the same shape as `error.schema.json` (code, problem, fix, optional
  path and details). `troupe.core.notices` declares each notice code once, as `CODES` does for errors. Reads return
  their notices alongside their results. A surface decides how to show them.
- New notices: `events.other-branch`, `events.order-rebuilt`, `events.incomplete-batch`.
- New errors (all exit 1): `events.stream-forked`, `events.settle-incomplete`, `events.missing-parent`,
  `events.malformed-record`, `events.unknown-format`, `events.lineage-invalid`, `identity.unresolved`,
  `identity.invalid-override`, `identity.ambiguous`, `identity.unknown-source`, `events.cause-unknown`, `command.timeout`, `command.not-found`,
  `command.output-too-large`, `environment.policy-invalid`, `vcs.failed`, and `events.unknown-store` and
  `vcs.unknown-adapter` for loading an adapter by a name that isn't installed.
- `environment.policy-invalid` wraps `EnvironmentPolicyError`, naming the variable and the reason. Today only
  troupe's own code can hit it, by narrowing wrongly or passing an explicit value for a forbidden name. Once
  `settings` lets config narrow a policy, a person can.
- The library's `IntegrityError` passes through the recorder unchanged, because the library's optimistic
  concurrency depends on it. The service turns it into `events.version-conflict` for surfaces.

### D13. `eventsourcing` and the bundled adapters run in process (#37)

Decision #37 (owner, 2026-10-12): every port is defined in core and has two transports, direct (in-process Python)
and JSON-RPC (out of process, through one generic bridge to the same port). **What ships in the box runs direct.**
That covers core, the bundled first-party adapters, and the libraries troupe pins. Plugins acquired by config run over
JSON-RPC.

For this change:
- **This change's bundled adapters run direct.** That's the text recorder (`troupe-store-text`), the git and
  filesystem VCS adapters, and the local identity sources, all loaded by entry point (D1).
- **`eventsourcing` runs in process** as a library troupe pins. It's pinned `>=9.5.5,<9.6`, so a minor release that
  changes the suite is taken deliberately.
- **In process means trusted** (#37, guardrail 1). A direct adapter could get around the event-store service and its
  lineage checks. That's acceptable because only code that ships with troupe runs direct here. The check in D1 (no
  surface imports a recorder) keeps troupe's own surfaces honest.
- **Not in this change:** the JSON-RPC transport for these ports, the generic bridge, the transport listing and
  policy, and running each port's conformance suite against both transports. Those are later Features under #37.
  The ports here are already schema-first where they cross a boundary (lineage, records, notices in `protocol/`), so
  the bridge can serve them later without a format change.

### D-Runner. What this change assumes about the runner contract (#34)

Checked against the runner-contract change's design.md (at `914ffc2`, its "Assumptions about the event format"),
and against its `troupe.platform.processes` API (at `eab458c` and `46dd1b6`), which this change builds on (D11). This
change assumes the following:

1. **troupe records, runners don't.** A runner's JSON-RPC stream (init, turns, tool calls, result, failure) is read
   by troupe core. Change C turns it into domain events and records them through `troupe.core.events`. A runner
   never writes to the event store, and never sees lineage.
2. **The agent's identity is assigned by troupe** from the actor's configured name (`actor: {kind: agent, id,
   source: "troupe"}`). `via` stays the closed enum, and runs use `"runner"` (owner, 2026-10-12). The runner's name
   and version go in C's run-started payload. Anything the runner reports about itself (a model name, a session ID)
   is payload, not identity.
3. **Transcripts are referenced by content hash.** #34 stores raw transcripts in a gitignored local store, keyed by
   content hash. Events carry the reference as payload, and the store treats it as opaque. SHA-256 with the
   `sha256:` prefix is assumed, so references read the same as event IDs. If #34 picks another algorithm, nothing
   here breaks; only consistency is lost.
4. **Lineage time is when troupe recorded the event.** The runner's own timestamps are payload.
5. **A run is its own stream (owner, 2026-10-12).** The run ID is a UUID and is the originator ID. The store assigns
   versions 1..n in recording order. The runner's `seq` stays in the payload as the order within the run, and is
   not mapped to `originator_version`. A run produces tens to hundreds of events. Change C can record them as they
   stream (one batch per runner message) and the outcome as one final batch. Batches are all or nothing (D4), so a
   cancelled run never leaves half an outcome.
   - **Expectation on C:** recording twice is an error, not a no-op (owner, 2026-10-12). Because `seq` isn't the
     version, a retried run event would land at the *next* version with a different parent, so the store would
     neither refuse it nor deduplicate it. C's run aggregate therefore refuses a `seq` that isn't the next one it
     expects. The store's `events.version-conflict` still guards two writers racing for the same version.
6. **Outcome is derived, then recorded.** #34 derives the outcome from the stream, the effect check and the exit
   code together; the exit code alone never makes a run succeed (owner, 2026-10-12). This change records whatever
   outcome event C defines. It has no outcome type of its own.
7. **Notices are shared.** The runner contract's announcements (silences, retries) use `notice.schema.json` and
   `troupe.core.notices` from this change (D12). Whichever change lands second adopts the other's file.
8. **The artifact store** (`LocalArtifactStore`) is its own package with a `troupe.artifacts` entry point, the same
   pattern as D1, under `.troupe/local/artifacts/` (D2).
9. **Shared files and merging.** Both changes edit `pyproject.toml`, `uv.lock`, `troupe.core.defaults`,
   `troupe.core.errors.CODES` and `docs/platform.md`, in separate blocks, and this change builds on the runner
   contract's `platform/processes.py` (D11). Whichever lands second rebases onto main (never merges main in) and
   re-locks `uv.lock`.

These were compared with the runner contract's design on 2026-10-12, and the owner's decisions are folded in above.
Its points 3, 5 and 9 were revised to match (`via` is `"runner"`; `seq` stays in the payload; run ids are UUIDs).
One wording difference remains, recorded for the PR (task 10.1): its point 4 says the store refuses a run event
recorded twice as a duplicate version. That holds only when C retries with a stale version; a retry after reloading
lands at the next version, so it is C's run aggregate, refusing a `seq` that isn't the next one, that makes a
second recording an error (point 5 above).

## Risks / Trade-offs

- [Rescanning on every write gets slow as segments grow] → The scan reads only new bytes. It stats the directory and
  then only segments whose size changed. The 10,000-segment cold load is measured, and if it is too slow, a later
  change compacts committed segments.
- [Windows: appending while another process reads] → Segments are opened with CPython's default sharing, which
  allows concurrent readers and appenders. The two-process tests run in Windows CI.
- [A hand-merged conflict inside a segment] → It can't arise from troupe, because no two sessions share a file. If
  a person edits one anyway, a malformed line fails with the file and line.
- [`TROUPE_ACTOR` lets anyone claim any identity] → So can git config. Local identity is unsigned, so it is
  attribution, not authentication. Signed identities are out of scope, and the source is recorded, so an override
  is visible in history.
- [Equal-ID recordings are kept twice on disk] → That's the cost of never rewriting. Reads deduplicate, and
  `recordings(id)` shows both.
- [Followers re-run after an order rebuild] → Delivery is at-least-once anyway. Projections are rebuilt from 0. A
  follower with outside effects (later) has to be idempotent, which is already a requirement of at-least-once.
- [A git hook, or the user's fsmonitor setup, leaves a child holding git's pipes, so a local git call times out]
  → The timeout error names the git command and the limit, so it's loud, not a hang. `GIT_TIMEOUT_SECONDS` can be
  overridden.
- [git can't see what it needs because the policy is too tight, and identity falls through to the OS login] → The
  identity tests resolve `user.email` from a global config under a temporary `HOME` and `XDG_CONFIG_HOME` through the
  real policy, on all three platforms (D11).
- [Two worktrees of one repository record concurrently] → Each worktree is its own theatre directory with its own
  `local/`, and its own branch. They never share a segment or an order log.

## Migration Plan

No existing events or theatre layout exist, so there's nothing to migrate. The record `format` starts at 1. Pre-1.0,
a format change may bump it, and a reader then refuses old lines with `events.unknown-format`.
