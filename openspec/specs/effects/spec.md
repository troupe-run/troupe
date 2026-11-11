# effects Specification

## Purpose
Capability: `cap:effects`, `cap:config`

What an actor may change, declared in its config, and what troupe does with the declaration: how it's written, the
read-only default, how the files a run must change sit inside it, how a run's changes are audited against it after
the run, and the scratch space every run gets outside it. None of it is enforcement, which only a stage can give.

## Requirements

### Requirement: An actor declares its effects as three lists of patterns
An actor's `effects` SHALL be a group of up to three lists, `write`, `delete` and `move`, each of path patterns
relative to the theatre's root. A pattern SHALL match with `*` within one part of a path, `**` as a whole part across
any number of parts, and `?` for one character, the same language as the runner SDK's. Each list SHALL be set whole,
like any list in config.

#### Scenario: Declaring where an actor may write
- **WHEN** a person runs `troupe config set actors.tester.effects.write='["out/**"]'`
- **THEN** `tester`'s file holds `effects` with `write: ["out/**"]`, and no `delete` or `move`

#### Scenario: Deleting is declared on its own
- **WHEN** a person sets `actors.tester.effects.delete` to `["drafts/**"]`
- **THEN** `tester` may delete under `drafts/`, and may write nowhere

### Requirement: With nothing declared, an actor is read-only
An actor with no `effects`, or with every list absent or empty, SHALL declare no effect. It SHALL be able to read the
workspace, and every change it makes there SHALL be outside its declaration.

#### Scenario: An actor with no effects
- **WHEN** an actor has no `effects` and its run writes `out/a.txt`
- **THEN** the run's audit fails, naming `out/a.txt` and the `write` effect

### Requirement: A pattern that can't be meant is refused
A pattern SHALL be refused, recording nothing, when it's empty, absolute, contains `..`, `\`, `:`, a control
character, an empty part or `**` inside a part, or starts with `.git` or `.troupe` as its first part. The error SHALL name the actor, the list,
the pattern's position in it and the rule, and SHALL NOT repeat any part of the pattern. The actor schema's pattern and the runner SDK's SHALL accept exactly the same patterns.

#### Scenario: An absolute pattern
- **WHEN** a person sets `actors.tester.effects.write` to `["/tmp/**"]`
- **THEN** it is refused, naming `actors.tester.effects.write`, the pattern's position and that patterns are relative
  to the theatre, and saying runs get scratch space without declaring it, without repeating `/tmp/**`

#### Scenario: A pattern into troupe's own directory
- **WHEN** a person sets `actors.tester.effects.write` to `[".troupe/**"]`
- **THEN** it is refused, saying `.troupe/` is troupe's own and no effect can allow changing it

#### Scenario: The schema and the SDK agree
- **WHEN** generated patterns and near misses are checked by the actor schema's pattern and by the SDK's
- **THEN** both accept or both refuse each one

#### Scenario: A pattern holding a password
- **WHEN** a person runs `troupe config set --json 'actors.tester.effects.write=["https://user:<canary>@example.com/v1"]'`
- **THEN** it is refused with `config.invalid`, naming `actors.tester.effects.write`, and neither the standard error
  nor the client message holds the canary or `example.com`

### Requirement: Every expected file is covered by the declaration
Each path in an actor's `expect` SHALL match a `write` or a `move` pattern. An actor with an `expect` path that
neither matches SHALL be invalid, refused when it's set, and refused with `config.invalid` when it's performed. The
error SHALL name the `expect` list, the path's position in it and the `troupe config set` that declares a covering
pattern, with a placeholder for that pattern, and SHALL NOT repeat the path.

#### Scenario: Expecting a file the actor can't write
- **WHEN** a person sets `actors.tester.expect` to `["out/hello.txt"]` and `tester` declares no effects
- **THEN** it is refused, naming `actors.tester.expect`, item 1 and `actors.tester.effects.write`, and nothing is
  recorded

#### Scenario: Expecting a file inside a declared pattern
- **WHEN** a person sets `expect` to `["out/hello.txt"]` and `effects.write` to `["out/**"]` in one command
- **THEN** one change is recorded

#### Scenario: Expecting a file a move creates
- **WHEN** `tester` declares `move` for `docs/**` and expects `docs/a.md`
- **THEN** the actor is valid

#### Scenario: An actor that was valid before
- **WHEN** an actor recorded before this rule expects `out/hello.txt` and declares no effects, and a person performs it
- **THEN** it is refused with `config.invalid`, naming the path and the fix, and nothing is recorded

#### Scenario: An expected path holding a password
- **WHEN** a person sets `actors.tester.expect` to `["https://user:<canary>@example.com/x"]` and no effect covers it
- **THEN** it is refused with `config.invalid`, naming `actors.tester.expect` and item 1, and neither the standard
  error nor the client message holds the canary

### Requirement: Every run's changes are audited against its declaration
Once a run's runner has ended, whatever the run's outcome, troupe SHALL audit each file added, changed or removed in
its workspace since the run started. Every change the declaration doesn't allow SHALL fail the audit. The audit SHALL
run for every actor, whatever its `expect`, and for every run whose runner started. A run whose runner never started
SHALL have no audit. When the run's result is `ok`, the audit SHALL be part of its effect check.

#### Scenario: Expecting nothing still audits
- **WHEN** an actor has `expect: []`, declares no effects, and its run writes `out/a.txt`
- **THEN** the audit fails, and the run doesn't succeed

#### Scenario: A run that failed is audited
- **WHEN** an actor declares `write` for `out/**`, and its run changes `src/a.py` and then sends an `error` result
- **THEN** the run's audit names `src/a.py` and the `write` effect it needed

#### Scenario: A run whose runner never started
- **WHEN** a run's runner can't be started
- **THEN** the run has no audit

### Requirement: Each kind of change needs its own effect
A file added or changed SHALL need a `write` pattern matching it. A file removed SHALL need a `delete` pattern
matching it. A file removed and a file added with the same content SHALL count as one move, which needs a `move`
pattern matching both, unless `delete` and `write` allow each end on its own.

#### Scenario: Writing where declared
- **WHEN** an actor declares `write` for `out/**` and its run changes only `out/a.txt`
- **THEN** the audit passes

#### Scenario: A change outside the declaration
- **WHEN** an actor declares `write` for `out/**` and its run also changes `src/a.py`
- **THEN** the audit fails, naming `src/a.py` and the `write` effect it needed

#### Scenario: A delete with only write declared
- **WHEN** an actor declares `write` for `**` and its run removes `README.md`
- **THEN** the audit fails, naming `README.md` and the `delete` effect

#### Scenario: A move within what's declared
- **WHEN** an actor declares `move` for `drafts/**` and its run moves `drafts/a.md` to `drafts/old/a.md`
- **THEN** the audit passes

#### Scenario: A move whose destination isn't declared
- **WHEN** an actor declares `move` for `drafts/**` and `delete` for nothing, and its run moves `drafts/a.md` to
  `docs/a.md`
- **THEN** the audit fails, naming both paths and the `move` effect

### Requirement: The audit sees changes as git sees them
The audit SHALL count the files version control would record: tracked files and untracked files that aren't ignored.
It SHALL leave out ignored files, everything under `.git` and everything under `.troupe/`. For a worktree run it SHALL
compare the worktree with the commit it started from, counting changes the actor committed. For a run in the theatre
it SHALL compare the theatre with how it was when the run started, so a change someone else makes there during the
run counts as the run's.

#### Scenario: A build output that's ignored
- **WHEN** a run's actor declares no effects and its run writes `__pycache__/a.pyc`, which `.gitignore` ignores
- **THEN** the audit passes

#### Scenario: A file already changed before a run in the theatre
- **WHEN** `src/a.py` has uncommitted changes, and a run in the theatre whose actor declares no effects leaves it as
  it was
- **THEN** the audit passes

#### Scenario: Someone edits the theatre during a run
- **WHEN** a person changes `notes.md` in the theatre while a run in the theatre, whose actor declares no effects, is
  going
- **THEN** the audit fails, naming `notes.md`, and its message says a run in the theatre counts every change made
  during it

### Requirement: A failed audit fails the run and names every change
A failed audit SHALL fail the run's effect check, so the run doesn't succeed. Its error SHALL list each change outside
the declaration with its path, what happened to it and the effect it needed, and the `troupe config set` that would
declare it. A worktree run's changes SHALL be kept as they are for any failed run, to show, accept or discard.

#### Scenario: Two changes outside the declaration
- **WHEN** a run whose actor declares `write` for `out/**` changes `src/a.py` and removes `src/b.py`
- **THEN** the run's outcome is `failed`, and its error lists `src/a.py` needing `write` and `src/b.py` needing
  `delete`

#### Scenario: Both checks fail
- **WHEN** a run doesn't write its expected `out/hello.txt` and writes `src/a.py` outside its declaration
- **THEN** the run's error names both the missing file and the change outside the declaration

### Requirement: Every run gets scratch space outside its declaration
troupe SHALL make an empty scratch directory for each run before its runner starts, outside the theatre and the
run's worktree, and give its absolute path to the runner. Nothing in it SHALL need an effect, be audited, or reach the
theatre. troupe SHALL remove it when the run ends, whatever its outcome, and a failure to remove it SHALL be reported
as a warning naming the directory, not a failed run. Where it's made SHALL be a named setting.

#### Scenario: Writing to scratch
- **WHEN** a read-only actor's run writes a file in its scratch directory
- **THEN** the audit passes, and nothing in the theatre or the worktree changes

#### Scenario: Scratch is gone after the run
- **WHEN** a run that wrote files in its scratch directory ends `failed`
- **THEN** its scratch directory no longer exists

#### Scenario: Scratch is never inside the theatre
- **WHEN** the scratch setting names a directory inside the theatre
- **THEN** perform is refused before anything is recorded, naming the setting and the directory

### Requirement: The declaration and its audit are not enforcement
Declaring effects, a runner applying them, and a passing audit SHALL NOT make a run's effects count as enforced. A run
on the local stage SHALL record its effects as `unenforced` whatever it declares.

#### Scenario: A declared, audited run on the local stage
- **WHEN** an actor that declares `write` for `out/**` runs on the local stage and its audit passes
- **THEN** every event the run records has lineage saying its effects were `unenforced`

### Requirement: Changes outside the workspace are neither prevented nor detected
Without a stage that enforces effects, troupe SHALL NOT claim to prevent or detect changes a run makes outside its
workspace and scratch directory. The audit SHALL cover only the workspace. The local stage's refusal, the fix that
names `allow_unenforced_local_stage`, and the user docs on effects SHALL each say so.

#### Scenario: A run writes outside the workspace
- **WHEN** a run on the local stage writes a file in the person's home directory, outside its workspace, and changes
  nothing in the workspace its actor didn't declare
- **THEN** the audit passes, and the run's lineage says its effects were `unenforced`

#### Scenario: The local stage's refusal says what isn't covered
- **WHEN** a person performs an actor on the local stage with no policy set
- **THEN** the refusal says that changes outside the workspace are neither prevented nor detected there, and that
  only a stage that enforces effects contains them

### Requirement: A failed run's audit doesn't change its outcome
When a run's result isn't `ok`, or it sent none, its audit SHALL NOT change its outcome or its error: the run keeps
the one error it failed with. Its findings SHALL be recorded with the run's end, as for any run, and a worktree run's
changes SHALL be kept, to show, accept or discard. Its expected files SHALL NOT be checked.

#### Scenario: A failed run that changed a file outside its declaration
- **WHEN** a worktree run whose actor declares `write` for `out/**` changes `src/a.py` and sends an `error` result
- **THEN** its outcome is `failed` with `run.error-result`, its end records the audit naming `src/a.py` and `write`,
  and its changes are kept

#### Scenario: A timed-out run that changed a file outside its declaration
- **WHEN** a run whose actor declares no effects writes `notes.md` and is still going when its run timeout passes
- **THEN** its outcome is `timed-out` with `run.timeout`, and its end records the audit naming `notes.md` and `write`

#### Scenario: A cancelled run that removed a file outside its declaration
- **WHEN** a run whose actor declares `write` for `**` removes `README.md` and is then cancelled
- **THEN** its outcome is `cancelled` with no error, and its end records the audit naming `README.md` and `delete`

#### Scenario: A failed run that stayed inside its declaration
- **WHEN** a run whose actor declares `write` for `out/**` changes only `out/a.txt` and sends an `error` result
- **THEN** its end records an audit that found no change outside the declaration

#### Scenario: A failed run's expected file
- **WHEN** a run whose actor expects `out/hello.txt` sends an `error` result without writing it
- **THEN** its error is `run.error-result` alone, and doesn't name `out/hello.txt`

### Requirement: An audit that can't read the workspace says so
When the audit can't read the workspace's files, the run's end SHALL still be recorded, holding the audit's error in
place of its findings. For a run whose result is `ok`, the effect check SHALL fail with `effects.audit-failed`, naming
the error, so the run doesn't succeed. For any other run, the outcome and its error SHALL be unchanged.

#### Scenario: The workspace can't be read after an ok result
- **WHEN** a runner sends an `ok` result and exits 0, and reading the workspace's files for the audit fails
- **THEN** the run's outcome is `failed` with `effects.audit-failed`, and its end records the audit's error

#### Scenario: The workspace can't be read after a cancel
- **WHEN** a run is cancelled, and reading the workspace's files for the audit fails
- **THEN** the run's outcome is `cancelled`, and its end records the audit's error
