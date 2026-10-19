# Spec Delta

## MODIFIED Requirements

### Requirement: Pages about unbuilt behaviour invent nothing
A page SHALL describe unbuilt behaviour only as far as a decided issue or an accepted spec settles it. Where
something it covers is still undecided, the page SHALL say so and link the open issue that will decide it, opening
one when none exists, and SHALL NOT describe a design for it.

#### Scenario: A page about the house
- **WHEN** a reader opens the house's page before the house is built
- **THEN** the page says that the house isn't built yet
- **AND** the page describes what #73 and #14 decided about the house, and links the open issue for what they leave
  open

#### Scenario: A page about runs
- **WHEN** a reader opens the performances and runs page
- **THEN** what it says about `troupe perform`, `status` and `logs` is what the CLI does today
- **AND** it says that `troupe perform` runs one actor today, not a performance of the whole process

#### Scenario: A page about something nobody has decided
- **WHEN** a reader opens the flows page while no issue decides how flows work
- **THEN** the page gives only the decided definition, says the rest isn't decided yet, and links the issue that
  will decide it
