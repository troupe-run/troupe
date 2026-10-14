# platform Specification

## Purpose

The single seam for OS-specific behaviour, so that troupe's file writes, locking, child processes, interrupts,
directory watching and path display behave the same on Linux, macOS and Windows. Later: daemon IPC.

## Requirements

### Requirement: Supported platforms
Every requirement in this capability SHALL hold on Linux, macOS and Windows. A platform difference SHALL be handled
inside this capability, so callers see one behaviour.

#### Scenario: The same tests pass on every platform
- **WHEN** the platform test suite runs on Linux, macOS and Windows
- **THEN** every test passes on each, and none is skipped for a missing platform implementation

### Requirement: Atomic file replacement
Replacing a file's contents SHALL be atomic: any reader sees either the complete old contents or the complete new
contents, never a partial file. The new file SHALL keep the original file's permission bits.

#### Scenario: Reader never sees a partial write
- **WHEN** a file is replaced while another process reads it repeatedly
- **THEN** every read returns either the complete old contents or the complete new contents

#### Scenario: Permissions are kept
- **WHEN** a file with non-default permission bits is replaced
- **THEN** the replaced file has the same permission bits

### Requirement: A failed replacement changes nothing
If a replacement fails at any point, the original file SHALL be unchanged and no temporary file SHALL be left
behind.

#### Scenario: Write fails part-way
- **WHEN** writing the new contents fails before the replacement completes
- **THEN** the original file's bytes are unchanged
- **AND** the directory contains no leftover temporary file

### Requirement: Replacing a file that is open elsewhere is bounded and announced
When the target file can't be replaced yet because another process has it open, the replacement SHALL retry, say
which file it is waiting for, and give up after a timeout with an error naming the path and the fix. It SHALL NOT
wait silently or indefinitely, and SHALL NOT leave a partial file.

#### Scenario: Target held open by another process
- **WHEN** a file is replaced while another process holds it open in a way that blocks replacement
- **THEN** troupe reports which file it is waiting for
- **AND** if the file is still held when the timeout passes, the replacement fails with an error naming the path
- **AND** the original file is unchanged and no temporary file is left

### Requirement: Lock waits are bounded and announced
A process waiting for a lock held by another process SHALL say what it is waiting for, and SHALL give up after a
timeout with an error naming the lock and the fix. It SHALL NOT wait silently or indefinitely.

#### Scenario: Lock held by another process
- **WHEN** a process tries to take a lock that another process holds
- **THEN** it reports which lock it is waiting for before the wait becomes noticeable
- **AND** if the lock is not released within the timeout, it fails with an error naming the lock

#### Scenario: Timeout comes from a named setting
- **WHEN** the lock timeout is read
- **THEN** its default value is defined in one named place and can be overridden

### Requirement: A process cannot deadlock on its own lock
Taking a lock that the same process already holds SHALL fail immediately with an error, rather than wait.

#### Scenario: Nested acquisition
- **WHEN** a process that holds a lock tries to take the same lock again
- **THEN** the attempt fails immediately with an error naming the lock

### Requirement: Paths are shown in a friendly full form
Any path shown to a user SHALL be absolute, with the user's home directory abbreviated to `~`. It SHALL NOT be shown
as `.` or as a path relative to the working directory.

#### Scenario: Path under the home directory
- **WHEN** a path inside the user's home directory is shown
- **THEN** it is shown as `~` followed by the platform's path separator and the rest of the path

#### Scenario: Path outside the home directory
- **WHEN** a path outside the user's home directory is shown
- **THEN** it is shown as an absolute path

#### Scenario: Current directory
- **WHEN** the path to show is the current working directory
- **THEN** it is shown in full form, not as `.`

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

### Requirement: A child's end says whether troupe's kill ended it
After a child process has ended, the platform seam SHALL say whether troupe's kill ended it. This SHALL be true only
when troupe killed the child and the child's exit status is the one that kill produces, on Linux, macOS and Windows.
On Windows, a kill SHALL end the child with an exit code troupe names, distinct from the codes a program commonly
exits with.

#### Scenario: A child troupe killed
- **WHEN** troupe kills a running child and waits for it
- **THEN** the seam says the kill ended it

#### Scenario: A child that exited before a late kill
- **WHEN** a child exits with code 0 and troupe then kills it before it has seen the exit
- **THEN** the child's exit code is 0 and the seam says the kill did not end it

#### Scenario: A child that exits with the kill's status by itself
- **WHEN** a child that troupe never killed ends with the same exit status a kill produces
- **THEN** the seam says the kill did not end it

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

### Requirement: A directory can be watched for changes
Watching a directory SHALL wake a waiter when a file directly inside it is created, grows, is replaced or is
removed, by any process. A change made between two waits SHALL NOT be lost: the next wait returns at once. A wait
SHALL take a timeout and SHALL say whether anything changed. It MAY report a change that wasn't one, never miss one.

#### Scenario: Another process appends to a file
- **WHEN** a process waits on a watched directory and another process appends a line to a file in it, five times
- **THEN** each wait returns saying something changed, and the median delay, measured from when the append returned,
  is under 0.25 s

#### Scenario: Another process creates a file
- **WHEN** a process waits on a watched directory and another process creates a file in it
- **THEN** the wait returns saying something changed, before its timeout

#### Scenario: A file is removed
- **WHEN** a file in a watched directory is removed while a process waits
- **THEN** the wait returns, saying something changed

#### Scenario: A change between waits is kept
- **WHEN** a file in a watched directory grows while nobody is waiting, and then a process waits
- **THEN** the wait returns at once, saying something changed

#### Scenario: Nothing changes
- **WHEN** a process waits on a watched directory with a timeout and nothing in it changes
- **THEN** the wait returns after the timeout, saying nothing changed

### Requirement: Watching uses bounded resources
Watching a directory SHALL hold a fixed number of OS handles, whatever the number of files in the directory.
Closing a watch SHALL release them and SHALL wake any wait on it.

#### Scenario: A directory with many files
- **WHEN** a directory holding 10,000 files, more than the default open-file limit on Linux and macOS, is watched,
  and one of them grows
- **THEN** the watch is set up and the wait returns, saying something changed

#### Scenario: Closing wakes a waiter
- **WHEN** a watch is closed while another thread waits on it
- **THEN** that wait returns at once

### Requirement: A directory that can't be watched fails clearly
When a directory can't be watched (it doesn't exist, the OS refuses the watch or has no watches left, or the
platform's watching service won't start), watching SHALL fail with an error naming the directory and the reason,
never return a watch that doesn't wake.

#### Scenario: The directory doesn't exist
- **WHEN** a directory that doesn't exist is watched
- **THEN** watching fails with an error naming the directory

#### Scenario: The OS refuses the watch
- **WHEN** the OS refuses to set up the watch
- **THEN** watching fails with an error naming the directory and the OS's reason
