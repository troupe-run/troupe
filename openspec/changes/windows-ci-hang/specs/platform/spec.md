## MODIFIED Requirements

### Requirement: Killing a child kills its whole process tree
A child process SHALL start in its own process group (or the platform's equivalent), so that killing it also kills
every process it started, including grandchildren, on Linux, macOS and Windows. This SHALL hold for a grandchild the
child starts the moment it begins running, before troupe could act, whether the child was started to be talked to
or run to completion.

#### Scenario: Grandchild is killed
- **WHEN** a child that has started a grandchild process is killed
- **THEN** both the child and the grandchild are no longer running

#### Scenario: A grandchild started straight away is killed
- **WHEN** a child starts a grandchild as the first thing it does, the grandchild holds the child's output open, and
  the child is then killed
- **THEN** the child and the grandchild are both no longer running, and waiting for the child ends

#### Scenario: A command run to completion that starts a grandchild straight away
- **WHEN** a command run to completion starts a grandchild as the first thing it does and is still running when its
  timeout passes
- **THEN** the command and the grandchild are both killed, and the failure names the command and the timeout
