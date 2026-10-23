# Spec Delta

## Purpose

Defines where a run works, and what happens to what it changed. A run gets its own git worktree, where its changes
are captured as a diff, and the person can see, accept or discard them, without anything the actor wrote reaching
the theatre unasked.

## ADDED Requirements

### Requirement: A worktree run works in its own worktree at HEAD
A run whose actor's workspace is `worktree` SHALL work in a new git worktree of the theatre's repository, made for
that run at `.troupe/local/worktrees/<run-id>/`, with HEAD detached at the theatre's HEAD commit. Before the runner
starts, every file in the worktree SHALL be what checking out that commit writes, and the worktree SHALL hold no
other file.

#### Scenario: The actor sees HEAD
- **WHEN** a theatre whose HEAD has `src/a.txt` with `one` performs an actor with workspace `worktree`, and the
  scripted runner reads `src/a.txt`
- **THEN** the runner runs in `.troupe/local/worktrees/<run-id>/` and reads `one`

#### Scenario: Two runs, two worktrees
- **WHEN** two runs of worktree actors are performed one after the other
- **THEN** each run has its own worktree, and neither sees what the other wrote

#### Scenario: The theatre is untouched
- **WHEN** a worktree run writes `out/hello.txt` and changes `src/a.txt`
- **THEN** the theatre's own `out/hello.txt` doesn't exist and its `src/a.txt` is unchanged

### Requirement: Uncommitted changes are left out, with a warning
A worktree run SHALL start from HEAD even when the theatre has uncommitted changes outside `.troupe/`: staged,
unstaged or untracked files that git doesn't ignore. It SHALL then send the notice `workspace.uncommitted-unseen`, saying the actor won't see
them and that accepting may conflict with them, and it SHALL still run. The run's start SHALL record that the theatre
was dirty.

#### Scenario: An uncommitted edit
- **WHEN** a person has edited `src/a.txt` without committing it, and performs a worktree actor
- **THEN** the notice `workspace.uncommitted-unseen` is shown, naming how many paths differ from HEAD
- **AND** the run goes ahead, its runner reads `src/a.txt` as it is in HEAD, and its start records that the theatre
  was dirty

#### Scenario: A clean theatre
- **WHEN** the theatre has no uncommitted changes outside `.troupe/`, such as when only troupe's own uncommitted
  events are there
- **THEN** no `workspace.uncommitted-unseen` notice is sent, and the run's start records that the theatre was clean

### Requirement: Files that match HEAD are cloned copy-on-write
When the worktree is made, each file that is the same in the theatre and in HEAD SHALL be cloned from the theatre
through the platform seam, copy-on-write where the filesystem supports it. Each other file SHALL be checked out from
git. The run's start SHALL record the clone mechanisms that were used.

#### Scenario: On APFS
- **WHEN** a worktree is made on macOS on an APFS volume
- **THEN** the files that match HEAD are cloned with `clonefile`, and the run's start records that mechanism

#### Scenario: On a filesystem without clones
- **WHEN** a worktree is made on a filesystem that can't clone, such as ext4
- **THEN** the files are copied, the worktree still matches HEAD, and the run's start records `copy`

#### Scenario: A file edited while it is cloned
- **WHEN** a file changes in the theatre after troupe found it matched HEAD and before it was cloned
- **THEN** the worktree's copy is checked out again from HEAD before the runner starts

### Requirement: A worktree needs git and a commit
A worktree run SHALL be refused before anything runs or is recorded when the theatre's VCS can't make a worktree,
with `vcs.worktrees-unsupported`, or when the theatre has no commit yet, with `workspace.no-head`. Each fix SHALL
name the actor's `workspace` setting and the value `theatre`.

#### Scenario: The plain-filesystem adapter
- **WHEN** a theatre on the plain-filesystem VCS adapter performs an actor whose workspace is `worktree`
- **THEN** it is refused with `vcs.worktrees-unsupported`, and the fix names `actors.<name>.workspace=theatre`
- **AND** no runner is started and nothing is recorded

#### Scenario: A repository with no commits
- **WHEN** a theatre with no commit yet performs a worktree actor
- **THEN** it is refused with `workspace.no-head`, and the fix says to commit or to set `workspace` to `theatre`

### Requirement: A run's changes are captured when it ends
When a worktree run ends, whatever its outcome, troupe SHALL capture the worktree's changes against its starting
state, as git sees it, as a git binary diff. It SHALL store the diff as an artifact, and record it in the run's end by reference, with the base
commit and the number of files added, modified and deleted. Changes the actor committed in the worktree SHALL count
as changes. A run with nothing changed SHALL record no diff and state `none`.

#### Scenario: A run that changes files
- **WHEN** a worktree run adds `out/hello.txt`, modifies `src/a.txt` and deletes `src/b.txt`, then succeeds
- **THEN** its end records a `sha256:` reference to the diff, the base commit, and 1 added, 1 modified and 1 deleted
- **AND** the diff's artifact applies to the base commit to give exactly the worktree's files

#### Scenario: A failed run's changes
- **WHEN** a worktree run writes `out/partial.txt` and then ends `failed`
- **THEN** its end still records the diff, with 1 file added

#### Scenario: A binary file
- **WHEN** a worktree run writes a file holding bytes that aren't text
- **THEN** the diff carries it, and accepting gives the theatre that file byte for byte

#### Scenario: The actor committed
- **WHEN** a worktree run commits a change to `src/a.txt` in its worktree and leaves another change uncommitted
- **THEN** the diff holds both, measured from the base commit

#### Scenario: A file git would normalise
- **WHEN** HEAD holds a file in a form git would normalise, such as CRLF under an `eol=crlf` attribute, so git lists
  it as modified in every checkout, and a worktree run doesn't touch it
- **THEN** the run starts, and its diff doesn't hold that file

#### Scenario: Nothing changed
- **WHEN** a worktree run changes no file
- **THEN** its end records no diff, and its changes are in state `none`

### Requirement: Changes under .troupe/ are left out of the diff
The captured diff SHALL leave out every path under `.troupe/`, and the run's end SHALL record how many such paths
changed. Accepting SHALL never write under `.troupe/`.

#### Scenario: An actor writes an event segment
- **WHEN** a worktree run changes a file under `.troupe/events/` and writes `out/hello.txt`
- **THEN** the diff holds only `out/hello.txt`, and the run's end records 1 path left out under `.troupe/`

### Requirement: Changes to the shared repository during a run are reported
For a worktree run, troupe SHALL compare the shared repository's refs, config and hooks from before the runner starts
with after it ends. It SHALL record each one that changed in the run's end, and send the notice
`workspace.shared-git-changed`, naming them, with hooks first, and saying that discard won't undo them. It SHALL NOT
claim the actor made them, only that they changed during the run.

#### Scenario: An actor creates a branch
- **WHEN** a worktree run runs `git branch scratch` in its worktree
- **THEN** its end records `refs/heads/scratch` as added, and the notice `workspace.shared-git-changed` names it

#### Scenario: An actor writes a hook
- **WHEN** a worktree run writes `pre-commit` into the repository's hooks directory
- **THEN** its end records the hook as added, and the notice names it first, saying it runs on the person's next
  commit

#### Scenario: Config changed
- **WHEN** a worktree run runs `git config core.hooksPath /tmp/elsewhere` in its worktree
- **THEN** its end records that the repository's config changed

#### Scenario: Nothing shared changed
- **WHEN** a worktree run changes only files in its worktree
- **THEN** its end records no shared changes, and no `workspace.shared-git-changed` notice is sent

### Requirement: The worktree is kept until the changes are accepted or discarded
A run's worktree SHALL stay in place after the run ends, including the files git ignores, until its changes are
accepted or discarded. It SHALL stay in place when the run was interrupted, too. troupe SHALL NOT remove a worktree
for any other reason.

#### Scenario: Ignored output survives the run
- **WHEN** a worktree run writes `build/out.bin`, which git ignores, and ends
- **THEN** `build/out.bin` is still in the run's worktree, and `status <run>` names the worktree's path

### Requirement: A run's changes can be shown
`diff` SHALL return a run's captured diff, read from the artifact store and verified against its reference, together
with its base commit and counts. A run with no changes SHALL return no diff and state `none`. A run that isn't ended
SHALL be refused with `run.not-ended`.

#### Scenario: Showing a run's diff
- **WHEN** a person asks for the diff of a run that changed `src/a.txt`
- **THEN** the diff it returns is the artifact the run's end references, byte for byte

#### Scenario: A running run
- **WHEN** a person asks for the diff of a run that is still `running`
- **THEN** it is refused with `run.not-ended`

#### Scenario: A run in the theatre
- **WHEN** a person asks for the diff of, accepts or discards a run whose workspace was `theatre`
- **THEN** it is refused with `run.not-a-worktree`, saying its changes are already among the person's files

### Requirement: Accepting applies the changes to the working tree, all or nothing
`accept` SHALL apply a run's captured diff to the theatre's working tree as unstaged changes, without touching the
index, HEAD or any branch. When any part of the diff doesn't apply cleanly, it SHALL be refused with
`run.changes-conflict`, naming the files that don't apply, the diff's reference and the worktree's path, and it SHALL
change no file. Once the diff has applied, the run's worktree SHALL be removed.

#### Scenario: A clean accept
- **WHEN** a person accepts a run that modified `src/a.txt` and added `out/hello.txt`
- **THEN** the theatre's `src/a.txt` and `out/hello.txt` are as the run left them, unstaged
- **AND** nothing was staged or committed, and the run's worktree is gone

#### Scenario: The person changed the same lines since
- **WHEN** a person edits the lines of `src/a.txt` the run changed, and then accepts the run
- **THEN** it is refused with `run.changes-conflict`, naming `src/a.txt`, the diff's reference and the worktree
- **AND** no file in the theatre changed, and the worktree is still there

#### Scenario: Line endings round-trip
- **WHEN** a file the attributes check out with CRLF line endings is changed by a run and accepted, on Linux, macOS
  and Windows
- **THEN** the theatre's file has CRLF line endings and the run's content

### Requirement: Discarding removes the worktree
`discard` SHALL remove a run's worktree and change nothing in the theatre's working tree. The diff's artifact SHALL be
kept. Discarding an interrupted run, or a run whose changes are `none`, SHALL remove its worktree too.

#### Scenario: Discarding a run
- **WHEN** a person discards a run that changed `src/a.txt`
- **THEN** the run's worktree is gone, the theatre's `src/a.txt` is unchanged, and the run's changes are `discarded`

#### Scenario: Discard says what it doesn't undo
- **WHEN** a person discards a run, or reads `troupe discard --help`
- **THEN** it says that discarding removes the worktree's files, and doesn't undo branches, tags, stashes, config,
  hooks or pushes the actor made in the shared repository

#### Scenario: Discarding an interrupted run
- **WHEN** a person discards a run that is `interrupted`
- **THEN** its worktree is removed and its discard is recorded

### Requirement: Accepting and discarding are recorded, and final
Accepting or discarding a run's changes SHALL be recorded on the run's stream with the person who did it as the
actor, via `cli`, no `stage`, and the reason given. Once a run's changes are accepted or discarded, a second accept or
discard SHALL be refused with `run.changes-settled`, naming what was done and when. Accepting a run that isn't ended,
or whose changes are `none`, SHALL be refused, with `run.not-ended` or `run.no-changes`.

#### Scenario: Who accepted
- **WHEN** a person whose identity resolves to `ada@example.com` accepts a run with `--reason "looks right"`
- **THEN** the run's stream ends with the acceptance, whose lineage has actor `human` `ada@example.com`, via `cli`,
  reason `looks right`, and no `stage`

#### Scenario: Accept after discard
- **WHEN** a person discards a run's changes and then accepts them
- **THEN** the accept is refused with `run.changes-settled`, naming the discard

#### Scenario: Two accepts at once
- **WHEN** two `accept`s of the same run start at the same time
- **THEN** one applies the diff, and the other is refused with `run.changes-settled`

### Requirement: Accepting and discarding can be rehearsed
`accept` and `discard` SHALL take `rehearse`. A rehearsed accept SHALL check that the diff applies cleanly, and a
rehearsed discard SHALL make every check a discard makes and name the worktree it would remove. Neither SHALL change a file or record an event.

#### Scenario: Rehearsing an accept that would conflict
- **WHEN** a person rehearses accepting a run whose diff doesn't apply cleanly
- **THEN** it reports `run.changes-conflict`, naming the files, and no file or event changes

#### Scenario: Rehearsing a clean accept
- **WHEN** a person rehearses accepting a run whose diff applies cleanly
- **THEN** it reports the files it would change, and no file or event changes

### Requirement: A run's changes have a state
A run summary SHALL give a worktree run's changes a state: `pending` when the run's end recorded a diff and nothing
has settled it, `accepted` or `discarded` once that is recorded, `none` when the run changed nothing, and `uncaptured`
when its end, or no end, holds no diff because capturing failed or the run was interrupted. A run that didn't use a
worktree SHALL have no changes state.

#### Scenario: After a run
- **WHEN** a worktree run that changed one file has ended
- **THEN** `status <run>` shows its changes as `pending`, with the diff's reference and the worktree's path

#### Scenario: A run in place
- **WHEN** a run's actor has workspace `theatre`
- **THEN** its summary has workspace `theatre` and no changes

#### Scenario: An interrupted run
- **WHEN** a worktree run's `perform` is killed
- **THEN** `status <run>` shows its changes as `uncaptured`, with the worktree's path

### Requirement: A capture that fails keeps the worktree and is recorded
When capturing a run's changes fails, the run's end SHALL still be recorded, with the capture's error in place of a
diff, and the worktree SHALL be kept. Accepting such a run, or an interrupted one, SHALL be refused with
`run.changes-uncaptured`, naming the worktree's path, so the person can look at it. Discarding it SHALL be allowed.

#### Scenario: git fails while capturing
- **WHEN** git fails while a run's changes are being captured
- **THEN** the run's end records the capture's error and no diff, and the worktree is still there
- **AND** accepting the run is refused with `run.changes-uncaptured`, naming the worktree

### Requirement: Workspace settings are named
Every limit that making, capturing, applying or removing a worktree uses SHALL be a named setting, with its default
in one place. A worktree operation that runs past its announce time SHALL be announced, and one that passes its
timeout SHALL fail, naming the operation and the timeout.

#### Scenario: A slow checkout
- **WHEN** making a worktree takes longer than its announce time
- **THEN** the person is told what troupe is waiting for and for how long
