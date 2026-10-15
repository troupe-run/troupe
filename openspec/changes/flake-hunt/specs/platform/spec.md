# Spec Delta

## MODIFIED Requirements

### Requirement: Replacing a file that is open elsewhere is bounded and announced
When the target file can't be replaced yet because another process has it open, the replacement SHALL retry, say
which file it is waiting for, and give up after a timeout with an error naming the path and the fix. It SHALL NOT
wait silently or indefinitely, and SHALL NOT leave a partial file.

#### Scenario: Target held open by another process
- **WHEN** a file is replaced while another process holds it open in a way that blocks replacement
- **THEN** troupe reports which file it is waiting for
- **AND** if the file is still held when the timeout passes, the replacement fails with an error naming the path
- **AND** the original file is unchanged and no temporary file is left

#### Scenario: A stall past the timeout is still announced
- **WHEN** the waiting process is stalled past both the announce time and the timeout before it could announce
- **THEN** it reports which file it is waiting for before it fails with the error naming the path

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

#### Scenario: A stall past the timeout is still announced
- **WHEN** the waiting process is stalled past both the announce time and the timeout before it could announce
- **THEN** it reports which lock it is waiting for before it fails with the error naming the lock

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

#### Scenario: The watched directory is removed
- **WHEN** the watched directory is removed, including on Windows while the watch still holds it open and it is
  pending deletion
- **THEN** the next wait fails with an error saying the directory is missing, not that it can't be watched

### Requirement: A directory can be watched for changes
Watching a directory SHALL wake a waiter when a file directly inside it is created, grows, is replaced or is
removed, by any process. A change made between two waits SHALL NOT be lost: the next wait returns at once. A wait
SHALL take a timeout and SHALL say whether anything changed. It MAY report a change that wasn't one, never miss one.

#### Scenario: Another process appends to a file
- **WHEN** a process waits on a watched directory and another process appends a line to a file in it, five times
- **THEN** each wait returns saying something changed, the fastest of the five delays, measured from when the
  append returned, is under 0.25 s, and their median is within 0.25 s plus an allowance for a loaded machine

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

#### Scenario: The platform's own wait ends early
- **WHEN** the platform's wait gives up before the timeout has passed by `time.monotonic()`, as Windows' timer can,
  or reports ready with nothing to read, as Linux's `poll` can
- **THEN** the wait waits again for what is left, and returns no earlier than its timeout
