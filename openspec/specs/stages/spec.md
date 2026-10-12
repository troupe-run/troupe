# stages Specification

## Purpose

Defines where an actor runs and whether troupe can enforce what it may touch there: the stage port, and the local
stage, which can't enforce any effect and so runs an actor only when policy allows it.

## Requirements

### Requirement: Stages are a port, found by name
A stage SHALL be a port defined in the core, with each implementation in its own package and found by name. Asking
for a stage that isn't installed SHALL fail with `stage.unknown`, naming the stages that are.

#### Scenario: An unknown stage
- **WHEN** troupe is asked for a stage named `docker` and only `local` is installed
- **THEN** it fails with `stage.unknown`, naming `local`

### Requirement: A stage admits an actor before it runs
Before a runner starts, the stage SHALL either admit the actor, saying whether its effects are enforced and, if not,
what allowed that, or refuse it. A refused actor SHALL NOT be run, and nothing SHALL be recorded.

#### Scenario: A refusal changes nothing
- **WHEN** a stage refuses an actor
- **THEN** no runner is started
- **AND** no event is recorded and no artifact is written

### Requirement: The local stage refuses unless policy allows it
The local stage SHALL treat every actor's effects as unenforceable, including an actor that declares none, because a
process on the host can touch anything the person can. It SHALL refuse every actor with `stage.effects-unenforced`
unless the policy setting `allow_unenforced_local_stage` is true.

#### Scenario: Default policy
- **WHEN** a person performs an actor on the local stage with no policy set
- **THEN** it is refused with `stage.effects-unenforced`
- **AND** the fix names the setting `allow_unenforced_local_stage` and how to set it

#### Scenario: Policy allows it
- **WHEN** a person performs an actor on the local stage with `allow_unenforced_local_stage` set to true from the
  environment
- **THEN** the actor runs
- **AND** every event the run records has lineage saying the stage is `local`, its effects were `unenforced`, and
  they were allowed by `allow_unenforced_local_stage` from `env`

### Requirement: The effect check is not enforcement
A passing post-run effect check SHALL NOT make a run's effects count as enforced. A run's admission and its effect
check verdict SHALL be recorded separately.

#### Scenario: A passing effect check on the local stage
- **WHEN** a run on the local stage succeeds with its effect check passing
- **THEN** its lineage still says its effects were `unenforced`

### Requirement: The local stage's workspace is the theatre
The local stage SHALL run the actor with the theatre's root directory as its workspace.

#### Scenario: Files land in the theatre
- **WHEN** a scripted runner on the local stage writes `out/hello.txt`
- **THEN** the file is at `out/hello.txt` under the theatre's root
