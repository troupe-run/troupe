# Proposal: event store and lineage

Issue: #35 (part of the walking skeleton, #33). Decisions: #1 (layout B, with its 2026-10-12 comment on abandoned
edits), #9 (identity, still open: this change proposes the default chain as a design decision).

## Why

Every later capability (runs, status, logs, config, gates) is built on events. troupe has no event store yet, and
the `eventsourcing` library's stock persistence is in-memory, SQLite or Postgres, which breaks the rule that
troupe's own state is text git can merge. The walking skeleton's third change (`perform`, `status` and `logs`)
can't start until the event format and lineage have settled, so this comes first, alongside the runner contract
(#34).

## What Changes

- **A text recorder for `eventsourcing`.** Append-only JSONL segments, one per session per branch, in a directory
  git tracks (`.troupe/events/`). Branches never conflict over event files, because no two sessions write the same
  file. It passes the library's own recorder test suite unmodified: aggregate, application, non-interleaving,
  tracking, process and infrastructure-factory cases, plus the opt-in subscription case.
- **Content-hash event IDs.** The hash covers what changed (stream, version, topic, parents and payload) and leaves
  out wall time and all lineage, so two clones that make the same change agree on its ID.
- **Local ordering.** Notification IDs live in a gitignored, per-branch order log. It is append-only and never
  renumbered. Events that arrive by a merge or a pull are appended in a deterministic order. Nothing in git is
  ever rewritten because of a merge.
- **Forks.** A stream appended to on two branches is detected and refused for loading, naming the stream, both
  heads and the files. A settling event with two parents ends the fork. It carries the settled state, so loading
  never applies two branches' events. The semantic three-way merge that decides that state arrives with config.
- **Events left behind by an abandoned edit** (#1, 2026-10-12). The store never classifies or drops events, so an
  edit and its revert both stay as recorded. Uncommitted events made on another branch are left out of every read,
  and troupe says so. An event whose parent is missing (an event file removed by hand) is refused, with the file,
  the missing parent and the fix.
- **Lineage on every event troupe records.** Actor (human, agent, or explicit `unknown`, never null), the identity
  source that resolved it, via, time, reason, change id (the correlation ID for everything that follows from one command),
  cause (the command, or the event it reacts to), approvals, and the VCS state the event was made in (VCS,
  branch, HEAD, the source file's before and after hashes). Defined as JSON Schema in `protocol/`. An event without
  valid lineage is refused before anything is written.
- **Identity: a pluggable source chain.** Default chain, agreed for #9 (owner,
  2026-10-12): `TROUPE_ACTOR`, then the VCS-configured identity (git `user.email`), then the OS login. If none
  resolves, the command fails. A source that finds nothing passes on. A malformed or ambiguous answer is an error,
  never a quiet fall-through. Lineage records which source answered. See design.md D9.
- **VCS adapters.** A port with two first-party adapters: git, and a plain filesystem with no branches.
- **Structured notices.** Reads can report conditions that aren't failures, such as events left out from another
  branch, or the order rebuilt. They're structured data like errors, so every surface can phrase them.

## Capabilities

### New Capabilities

- `event-store`: recording and reading events as mergeable text, including segments, content-hash IDs, local
  ordering, conformance with the library's recorder contract, forks and settling, events from other branches,
  missing parents and incomplete writes.
- `lineage`: what every recorded event says about its origin (actor, via, time, reason, change id, approvals, VCS
  state), its language-neutral schema, and refusing events without it.
- `identity`: resolving who is acting, through a pluggable, ordered chain of identity sources, and failing when
  nobody can be identified.
- `vcs`: the version-control port troupe reads the working tree's state through (branch, HEAD, whether a path is
  committed, the configured identity), with git and plain-filesystem adapters.

### Modified Capabilities

None. The `platform` behaviours the git adapter relies on (a bounded run that kills the whole process tree, and
environment policies) are specified and built by the runner contract (#34), which owns `troupe.platform.processes`.
This change's `vcs` tests prove the adapter uses them correctly. See design.md D11.

## Out of scope

- Keep-and-ask for abandoned edits (a later addition; the event format already carries what it needs).
- The hand-edit sweep that records a revert as an ordinary edit. It arrives with config, the first capability
  with hand-editable files (#6, #7). This change provides what it records into (design.md D7).
- The config projection and its semantic three-way merge.
- The house watching files (#5), personal config streams (#2), signed identities, mapping identities to people
  and roles (#9 question 3).
- Recording runs, and the `perform`, `status` and `logs` commands (#33 change C).
- Release packaging of the new adapter packages.

## Impact

- **New packages** (first-party in-process adapters, per the bootstrap design's D1): `troupe-store-text` (the
  recorder), `troupe-vcs-git`, `troupe-vcs-files` and `troupe-identity-local`. Ports and the event-store service
  live in `troupe.core`.
- **Dependencies:** `eventsourcing` 9.5.x (runtime, in `troupe` and `troupe-store-text`); `pycryptodome` (dev
  only: the library's test suite imports it).
- **troupe.platform:** nothing new of its own. The git adapter uses the runner contract's `processes` module
  (`run_to_completion`, `EnvironmentPolicy`), and declares its own environment policy (`GIT_ENVIRONMENT`).
- **protocol/:** `lineage.schema.json`, `event-record.schema.json` and `notice.schema.json`.
- **troupe.core:** new error codes, notice codes and named defaults, and docs (`docs/event-store.md`) checked
  against the defaults.
- **Theatre layout:** `.troupe/events/` (tracked) and `.troupe/local/` (gitignored by `.troupe/.gitignore`, which
  troupe writes only if it is missing).
- **Unblocks** #33 change C. The runner contract (#34) is developed in parallel; design.md states what this change
  assumes about it.
