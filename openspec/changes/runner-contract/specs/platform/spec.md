# Spec Delta

## ADDED Requirements

### Requirement: Child processes start in their own group with an explicit environment
Starting a child process SHALL place it in its own process group (or the platform's equivalent), so it and every
process it starts can be stopped together. The child SHALL receive only the environment variables the caller
names, plus the minimum the platform needs to start a process.

#### Scenario: Caller's variables only
- **WHEN** a child is started with one named variable while the parent has others
- **THEN** the child sees the named variable and none of the parent's others, apart from the platform minimum

#### Scenario: Platform minimum on Windows
- **WHEN** a Python child is started on Windows with no named variables
- **THEN** it starts and runs successfully

### Requirement: Killing a child kills its whole process tree
Killing a child process SHALL also kill every process it started, including grandchildren, on Linux, macOS and
Windows.

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
