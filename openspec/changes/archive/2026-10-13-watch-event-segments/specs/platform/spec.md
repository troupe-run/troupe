# Spec Delta

## ADDED Requirements

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
