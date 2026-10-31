# Spec Delta

## MODIFIED Requirements

### Requirement: A directory can be watched for changes
Watching a directory SHALL wake a waiter when a file directly inside it is created, grows, is replaced or is
removed, by any process. A change made between two waits SHALL NOT be lost: the next wait returns at once. A wait
SHALL take a timeout and SHALL say whether anything changed. It MAY report a change that wasn't one, never miss one.

#### Scenario: Another process appends to a file
- **WHEN** a process waits on a watched directory and another process appends a line to a file in it, five times,
  and then, while no delay so far is under 0.25 s, once more at a time for up to a 60 s allowance for a slow stretch
- **THEN** each wait returns saying something changed, the fastest of the delays, measured from when the append
  returned, is under 0.25 s, and the median of the first five is within 0.25 s plus an allowance for a loaded machine

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
