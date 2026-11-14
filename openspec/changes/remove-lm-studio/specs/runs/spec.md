## MODIFIED Requirements

### Requirement: Perform refuses an actor whose runner isn't installed
When an actor's runner is in troupe's table but its package isn't installed, `perform` SHALL refuse with
`runner.not-installed` before anything is recorded, naming the runner, its package and its extra. The fix SHALL say to
install `troupe-run[<extra>]` with the command on the install page, or, for a runner with no extra, to reinstall troupe
or run `uv sync` in a checkout of troupe.

#### Scenario: A library-backed runner that isn't installed
- **WHEN** a person performs an actor whose runner, `example`, is in the extra `example`, and its package isn't
  installed
- **THEN** it is refused with `runner.not-installed`, with details naming the runner, the package and `example`,
  and a fix naming `troupe-run[example]` and the install page
- **AND** nothing is recorded, and no run directory or worktree is made

#### Scenario: A base runner missing from a broken install
- **WHEN** a person performs an actor whose runner is `scripted`, and `troupe_runner_scripted` isn't installed
- **THEN** it is refused with `runner.not-installed`, with no extra in its details, and a fix naming the install page and
  `uv sync`

#### Scenario: Rehearsing
- **WHEN** a person runs `troupe perform <actor> --rehearse` for an actor whose runner isn't installed
- **THEN** it is refused with `runner.not-installed`, as a perform would be
