# Spec Delta

## ADDED Requirements

### Requirement: A child's environment is explicit and built from a declared policy
A child SHALL receive exactly the environment its caller passes; nothing SHALL be inherited implicitly. The
environment SHALL be built from the platform minimum plus a declared policy: variables selected from the parent by
exact name or by prefix, minus names never passed (exactly or by prefix), plus explicit values. An explicit value
for a never-passed name SHALL be refused with an error, not dropped or passed.

#### Scenario: Only selected variables pass
- **WHEN** a policy selects `A` exactly and `GIT_` by prefix, and the parent has `A`, `GIT_X` and `B`
- **THEN** the environment holds `A` and `GIT_X` and the platform minimum, and not `B`

#### Scenario: Never-passed names win
- **WHEN** a policy selects the prefix `GIT_` but never passes `GIT_DIR`, and the parent has `GIT_DIR`
- **THEN** the environment has no `GIT_DIR`
- **AND** if `GIT_DIR` is also given explicitly, building the environment fails with an error naming `GIT_DIR`

#### Scenario: Never-passed prefixes win
- **WHEN** a policy selects the prefix `GIT_` but never passes the prefix `GIT_INDEX`, and the parent has `GIT_INDEX_FILE`
- **THEN** the environment has no `GIT_INDEX_FILE`

#### Scenario: Names match case-insensitively on Windows
- **WHEN** a policy selects `Path` and the parent has `PATH`, on Windows
- **THEN** the environment holds it; on Linux and macOS it does not

#### Scenario: Caller's variables only
- **WHEN** a child is started with an environment naming one variable while the parent has others
- **THEN** the child sees the named variable and none of the parent's others, apart from the platform minimum

#### Scenario: Platform minimum on Windows
- **WHEN** a Python child is started on Windows with an empty policy and no explicit values
- **THEN** it starts and runs successfully

### Requirement: Environment policies can be narrowed but never widened
Each port or adapter SHALL declare its environment policy as a named default in one place. A policy SHALL offer
only narrowing: removing selected names or prefixes, or adding never-passed names or prefixes. Nothing SHALL widen a declared
policy.

#### Scenario: Narrowing removes
- **WHEN** a policy that selects `A` and `B` is narrowed to drop `B`
- **THEN** the narrowed policy selects `A` only

#### Scenario: Narrowing cannot add
- **WHEN** narrowing is asked to select a name, or a prefix wider than one, the policy does not select
- **THEN** it is refused with an error naming the name

### Requirement: Killing a child kills its whole process tree
A child process SHALL start in its own process group (or the platform's equivalent), so that killing it also kills
every process it started, including grandchildren, on Linux, macOS and Windows.

#### Scenario: Grandchild is killed
- **WHEN** a child that has started a grandchild process is killed
- **THEN** both the child and the grandchild are no longer running

### Requirement: Child output lines are not limited to 64 KiB
Reading a child's standard output line by line SHALL accept lines up to a maximum the caller sets, and a line
longer than that maximum SHALL be reported as an error naming the limit, not as a hang or a silent truncation.

#### Scenario: Line of several megabytes
- **WHEN** a child writes a 5 MiB line and the maximum is larger
- **THEN** the line is read whole

#### Scenario: Line over the maximum
- **WHEN** a child writes a line longer than the maximum
- **THEN** reading reports an error naming the maximum

### Requirement: A command can be run to completion within a bound
Running a short command to completion SHALL return its exit code and output, SHALL work whether or not the caller
is inside a running event loop, and SHALL never wait silently or without limit: a wait is announced after a set
time, and past the timeout or the output limit the whole process tree is killed and the failure is reported.

#### Scenario: Command finishes
- **WHEN** a command writes to standard output and standard error and exits with code 3
- **THEN** the result holds both outputs and the exit code 3

#### Scenario: Command passes its timeout
- **WHEN** a command, which has started a child of its own, is still running when the timeout passes
- **THEN** both are killed, and the failure names the command and the timeout and carries the output so far

#### Scenario: Output passes its limit
- **WHEN** a command writes more output than the limit
- **THEN** its process tree is killed and the failure names the limit

#### Scenario: Called from inside an event loop
- **WHEN** the command is run from a coroutine in a running event loop
- **THEN** it completes the same way as outside one

#### Scenario: A long wait is announced
- **WHEN** a command is still running when the announce time passes
- **THEN** the caller is told which command it is waiting for and how long it has waited
