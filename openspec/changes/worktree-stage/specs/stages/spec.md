# Spec Delta

## MODIFIED Requirements

### Requirement: The local stage's workspace is the theatre
The local stage SHALL run the actor in the workspace its `workspace` setting names: the run's own worktree for
`worktree`, the default, and the theatre's root directory for `theatre`. Neither one changes what the local stage
enforces: a worktree contains nothing, so the stage's admission, and the `stage` lineage of every event the run
records, SHALL be the same for both.

#### Scenario: Files land in the theatre
- **WHEN** a scripted runner, for an actor whose workspace is `theatre`, writes `out/hello.txt` on the local stage
- **THEN** the file is at `out/hello.txt` under the theatre's root

#### Scenario: Files land in the worktree
- **WHEN** a scripted runner, for an actor with no `workspace` set, writes `out/hello.txt` on the local stage
- **THEN** the file is at `out/hello.txt` under the run's worktree, and not under the theatre's root

#### Scenario: A worktree is still unenforced
- **WHEN** a worktree run on the local stage, allowed by `allow_unenforced_local_stage` from `env`, records an event
- **THEN** its lineage's `stage` names `local`, effects `unenforced`, and the setting and source that allowed it

### Requirement: A stage admits an actor before it runs
Before a runner starts, the stage SHALL either admit the actor, saying whether its effects are enforced and, if not,
what allowed that, or refuse it. A refused actor SHALL NOT be run, and nothing SHALL be recorded. The stage SHALL
admit the actor before any workspace is made, so a refused actor leaves no worktree.

#### Scenario: A refusal changes nothing
- **WHEN** a stage refuses an actor
- **THEN** no runner is started
- **AND** no event is recorded, no artifact is written, and no worktree is made
