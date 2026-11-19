## ADDED Requirements

### Requirement: The check runs the size gate everywhere
`scripts/check.py` SHALL run the size gate (troupe-run/infrastructure spec: quality-gates) on every run, local and on
every CI leg, scoped or full, against the same base as the complexity gate, with troupe's limits in
`quality-gates.toml`: a note for each changed file above 32 KiB, and a failure for a file the work adds or makes larger
above 48 KiB or above its own ceiling in `[size.allow]`. Each `[size.allow]` entry SHALL name the issue that splits its
file.

#### Scenario: A commit grows a file past the limit
- **WHEN** the guard runs the check before a commit that makes a file larger than 49,152 bytes, and the file has no
  ceiling of its own
- **THEN** the check fails at the size gate, naming the file and its size, and the commit is refused

#### Scenario: A file with its own ceiling
- **WHEN** a change edits `contributing/runners.md`, still under its ceiling in `[size.allow]`
- **THEN** the size gate passes, noting the file is above the warning

#### Scenario: A file no longer needs its allowance
- **WHEN** a split brings a file named in `[size.allow]` under 49,152 bytes
- **THEN** the size gate fails until the change removes its entry

#### Scenario: A delivered file
- **WHEN** infrastructure's delivery grows `scripts/guard.py`
- **THEN** no gate in troupe measures it, because `.github/guard-delivery.json` lists it
