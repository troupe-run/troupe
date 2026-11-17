# Spec Delta

## ADDED Requirements

### Requirement: The check runs the complexity gate everywhere
`scripts/check.py` SHALL run the complexity gate (troupe-run/infrastructure spec: quality-gates) on every run, local
and on every CI leg, with the thresholds in `quality-gates.toml`. It SHALL accept `--base <commit>` to name what the
work is judged against; without it, the work is judged against where it left `origin/main`.

#### Scenario: A local commit adds a complex function
- **WHEN** the guard runs the check before a commit that adds a function whose complexity is above the limit
- **THEN** the check fails at the complexity gate, naming the function, and the commit is refused

#### Scenario: Every CI leg judges against the pull request's base
- **WHEN** a ready pull request's legs run the check
- **THEN** each leg passes the pull request's base, and the complexity gate passes or fails the same way on every OS

### Requirement: One CI leg measures coverage and audits the lock file
CI's Linux leg with Python 3.15 SHALL run the coverage gate on a full check and the dependency-audit gate, by setting
`QUALITY_GATES_LEG=true`. No other leg, and no local run, SHALL measure coverage: the check SHALL fail, naming the
variable, when it's set outside GitHub Actions or to anything but `true`. A scoped check on the leg SHALL say coverage
wasn't measured.

#### Scenario: The coverage leg
- **WHEN** a ready pull request changing a package's source runs CI
- **THEN** the Linux 3.15 leg prints every package's coverage against its baseline, and fails if one is below it by
  more than the tolerance

#### Scenario: Coverage asked for locally
- **WHEN** someone runs `QUALITY_GATES_LEG=true uv run scripts/check.py` on their machine
- **THEN** the check stops before any gate, saying coverage runs on CI's coverage leg only and to unset the variable

### Requirement: Advisories no gate blocks on are reported weekly
troupe SHALL audit `uv.lock` on `main` every week and keep one "Dependency advisories" issue up to date, opened, updated
and closed as troupe-run/infrastructure's quality-gates spec says, and SHALL put a newly opened one on the troupe
roadmap board.

#### Scenario: A moderate advisory appears
- **WHEN** the weekly audit finds a moderate advisory and no report issue is open
- **THEN** it opens one listing the advisory, and the board job adds it to the board
