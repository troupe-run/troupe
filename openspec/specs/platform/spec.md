# platform Specification

## Purpose

The single seam for OS-specific behaviour, so that troupe's file writes, locking and path display behave the same
on Linux, macOS and Windows. Later: processes and signals, daemon IPC and file watching.

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
