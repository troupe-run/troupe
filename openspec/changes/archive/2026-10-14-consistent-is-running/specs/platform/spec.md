# Spec Delta

## ADDED Requirements

### Requirement: Whether a process has ended has one meaning on every platform
Asking whether a process is running SHALL answer one question on Linux, macOS and Windows: has it ended? It SHALL
say "running" when the process hasn't ended, including when the OS refuses access to it; "ended" only when the OS
reports no such process or that it has exited; and otherwise SHALL fail with an error naming the process id and
the OS error, never a guess.

#### Scenario: A live child is running
- **WHEN** a child process that is still running is asked about
- **THEN** it reads as running

#### Scenario: A process that has exited and been waited for has ended
- **WHEN** a child process has exited, its parent has waited for it, and its id is asked about
- **THEN** it reads as ended

#### Scenario: A refused process is running
- **WHEN** the OS refuses access to a process that exists, because it belongs to another user or is protected
- **THEN** it reads as running, on every platform

#### Scenario: An exited process still held open has ended on Windows
- **WHEN** on Windows a child has exited but its parent still holds a handle to it
- **THEN** it reads as ended

#### Scenario: An exit code equal to Windows' "still active" value has ended
- **WHEN** a child exits with code 259 and is asked about while its parent still holds it (Windows) or after it
  is waited for (Linux and macOS)
- **THEN** it reads as ended

#### Scenario: The OS can't say
- **WHEN** the OS fails the query for a reason that is neither "no such process" nor "access refused"
- **THEN** the query fails with an error naming the process id and the OS error

#### Scenario: A pid that can't name one process is refused
- **WHEN** the id asked about is zero, negative, larger than any platform's process ids, or not an integer
- **THEN** the query fails with an error naming the value, and no signal is sent

#### Scenario: An unreaped child on Linux and macOS is a documented limit
- **WHEN** on Linux or macOS a child has exited but its parent hasn't waited for it yet
- **THEN** it reads as running, and the platform documentation names this limit
