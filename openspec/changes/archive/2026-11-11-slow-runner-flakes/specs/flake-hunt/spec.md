## MODIFIED Requirements

### Requirement: The hunt can load the machine
The hunt SHALL keep a given number of CPUs busy for as long as its rounds run, and SHALL stop that load when it ends,
however it ends, including when its own process is killed, on every platform. With no load given, it SHALL add none.

#### Scenario: Load during the rounds
- **WHEN** the hunt runs with a load of 2
- **THEN** two busy processes run from before the first round starts until the last round ends, and none is left
  running afterwards

#### Scenario: Stopped part-way
- **WHEN** the person presses Ctrl-C during a hunt, or Ctrl-Break on Windows
- **THEN** the running rounds and the load stop, the summary of the rounds that finished is printed, and no process
  the hunt started is left running

#### Scenario: The hunt is killed
- **WHEN** the hunt's own process is killed while its load runs, so none of its own clean-up runs (`SIGKILL` on
  Linux and macOS, `TerminateProcess` on Windows)
- **THEN** every load process it started ends too, within a few seconds
