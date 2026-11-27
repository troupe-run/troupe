## ADDED Requirements

### Requirement: The first run says exit 4 is waiting, not failure
The first-run walkthrough SHALL say plainly that when `troupe perform` exits 4, the run succeeded and its work waits for
you at its gate, and that 4 isn't a failure. It SHALL agree with the CLI reference's exit-code table, which names 4
as `WAITING`.

#### Scenario: A reader sees exit 4
- **WHEN** a reader reaches the part of the first-run walkthrough where `troupe perform lead` ends
- **THEN** it says the run succeeded, that exit 4 means its work waits for you, and that it isn't a failure
- **AND** the CLI reference's exit-code table gives 4 as `WAITING`, a run that succeeded with work waiting at its gate
