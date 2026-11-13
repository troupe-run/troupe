## ADDED Requirements

### Requirement: A process id's namespace can be named
The platform seam SHALL name, as a token, the pid namespace this process's ids belong to: the same for two
processes to which a process id means the same process, and different across machines, pid namespaces and
restarts. When the OS can't say, there SHALL be no token, never a guess.

#### Scenario: The same namespace gives the same token
- **WHEN** a process and a child it starts each ask for the token
- **THEN** both get the same token, on Linux, macOS and Windows

#### Scenario: What the token is made of
- **WHEN** the token is read on Linux
- **THEN** it holds the pid namespace's identity and the boot id; on macOS and Windows, the host name and the boot
  time

#### Scenario: Asked twice, the token doesn't change
- **WHEN** one process asks for the token twice, some time apart
- **THEN** both answers are the same
