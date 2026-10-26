# cli Specification

## Purpose

Capability: `cap:cli`

The command-line surface of troupe: a thin client over the core's commands and queries, covering how it is
invoked, how global flags are parsed, and how results and errors are rendered and reported through exit codes.

## Requirements

### Requirement: Version reporting
`troupe --version` SHALL print the installed troupe version and the protocol version it carries to standard output
and exit 0, without needing a theatre, an identity or a running daemon.

#### Scenario: Version outside any theatre
- **WHEN** a user runs `troupe --version` in a directory with no `.troupe/`
- **THEN** standard output contains the installed version string
- **AND** the exit code is 0

#### Scenario: The protocol version
- **WHEN** a user runs `troupe --version` with a troupe that carries protocol 0.2.0
- **THEN** standard output names `protocol 0.2.0` after troupe's own version

### Requirement: Global flags are accepted anywhere
A global flag SHALL have the same effect whether it appears before or after the subcommand name.

#### Scenario: Flag before the subcommand
- **WHEN** a user runs `troupe --version`
- **THEN** the version is printed

#### Scenario: Same flag after a subcommand
- **WHEN** a user runs a subcommand with a global flag placed after the subcommand name
- **THEN** the result is the same as with the flag placed before the subcommand name

### Requirement: Dash-leading values follow the `--` convention
A positional value that begins with `-` SHALL be accepted only after a `--` separator. Without it, the CLI SHALL
treat the value as an option and report a usage error that names the `--` fix. A separator with nothing after it
SHALL change nothing: the line SHALL give the same result as the same line without it.

#### Scenario: Dash-leading value without separator
- **WHEN** a user passes a positional value `-5` without a preceding `--`
- **THEN** the CLI exits with the usage-error code
- **AND** the message names the value and says to put `--` before it

#### Scenario: A separator with nothing after it, once the positionals are filled
- **WHEN** a user runs `troupe status x --json --`
- **THEN** it parses exactly as `troupe status x --json` does, with run `x` and JSON output
- **AND** it is not refused as `usage.invalid`

#### Scenario: A trailing separator never changes the outcome
- **WHEN** a command line that contains no `--` gets one `--` added at its end, after the command
- **THEN** the result is the same as without it: the same parsed arguments, or the same usage error code

#### Scenario: A `--` after the separator is a value
- **WHEN** a user runs `troupe status x -- --`
- **THEN** the second `--` is a positional value, and it fails with `usage.extra-argument`, naming `--`

### Requirement: Errors are rendered from structured data
Every error SHALL originate as structured data with a problem, an optional path, and a fix. The CLI SHALL render it
to standard error, write nothing to standard output, and exit non-zero. The structured shape SHALL be defined once,
in the language-neutral protocol, so other surfaces can render the same error their own way.

#### Scenario: An error names the problem and the fix
- **WHEN** a command fails
- **THEN** standard error contains the problem and the fix
- **AND** it contains the path when the error concerns a file or directory
- **AND** standard output is empty
- **AND** the exit code is non-zero

#### Scenario: Error data matches the protocol schema
- **WHEN** any error the CLI can produce is serialised as data
- **THEN** it validates against the protocol's error schema, including the details schema for its code

### Requirement: Usage errors and unknown commands
A usage error SHALL exit with code 2. An unknown subcommand or flag SHALL be reported as a usage error that names
what was not recognised and, where one exists, the closest valid alternative.

#### Scenario: Unknown subcommand with a near match
- **WHEN** a user runs `troupe verison`
- **THEN** the exit code is 2
- **AND** the message names `verison` as unknown and suggests `--version`

#### Scenario: Unknown flag
- **WHEN** a user passes a flag the CLI does not define
- **THEN** the exit code is 2
- **AND** the message names the flag

#### Scenario: Unknown flag after a command
- **WHEN** a user runs `troupe status --bogus`
- **THEN** the exit code is 2
- **AND** the message names `--bogus` and `troupe status`
- **AND** the fix, when there is no near match, points at `troupe status --help`

#### Scenario: A separator before any command
- **WHEN** a user runs `troupe -- echo x`, with `--` before the command
- **THEN** the exit code is 2
- **AND** the message says `--` comes before any command, and the fix says to put the command first

#### Scenario: An empty argument where the command goes
- **WHEN** a user runs `troupe '' status`
- **THEN** the exit code is 2
- **AND** the error says an empty argument is not a troupe command, and validates against the protocol's error schema

### Requirement: A usage problem carries no surface prefix
A usage error's problem SHALL NOT begin with a surface's name or prefix, such as `troupe:`. Each surface SHALL add
its own prefix when it renders the error, so the CLI prints `troupe: ` exactly once at the start of the problem.

#### Scenario: The prefix appears once
- **WHEN** a person runs `troupe perform tester --runner scripted`
- **THEN** the first line of standard error starts with `troupe: ` and does not contain `troupe: troupe:`
- **AND** the error's problem data does not start with `troupe:`

#### Scenario: Every usage shape is prefix-free
- **WHEN** the CLI reports any usage error, whether an unknown command, an unknown flag, a dash-leading value, a
  missing argument, a missing one-of, conflicting options, an extra argument, a missing value, an invalid value or
  the backstop
- **THEN** its problem does not start with `troupe:`

### Requirement: A usage error names the command it concerns and points at its help
A usage error found after the command line has chosen a command SHALL name that command (for example
`troupe perform`) in its problem and in its details, and its fix SHALL point at that command's help
(`troupe perform --help`) unless it gives a more specific fix. A usage error found before any command is chosen SHALL
point at `troupe --help`.

#### Scenario: A command's usage error points at the command's help
- **WHEN** a person runs `troupe logs` with no run
- **THEN** the problem names `troupe logs`
- **AND** the fix says to run `troupe logs --help`

#### Scenario: An error before any command points at the root help
- **WHEN** a person runs `troupe nosuchthing`
- **THEN** the fix points at `troupe --help`

### Requirement: Each usage shape has its own code
Each usage shape SHALL have its own code, exiting 2, with details naming the command and what was wrong:
`usage.missing-argument`, `usage.missing-one-of`, `usage.conflicting-options`, `usage.extra-argument`,
`usage.missing-value` and `usage.invalid-value`. The scenarios define each shape.

#### Scenario: A required option is missing
- **WHEN** a person runs `troupe perform tester --no-effect-check`
- **THEN** it fails with `usage.missing-argument`, naming `troupe perform` and `--runner`

#### Scenario: A required positional is missing
- **WHEN** a person runs `troupe logs`
- **THEN** it fails with `usage.missing-argument`, naming `troupe logs` and the run

#### Scenario: A required one-of group got none
- **WHEN** a person runs `troupe perform tester --runner scripted`
- **THEN** it fails with `usage.missing-one-of`, naming `troupe perform`, `--expect` and `--no-effect-check`

#### Scenario: Two exclusive options given
- **WHEN** a person runs `troupe perform tester --runner scripted --expect out.txt --no-effect-check`
- **THEN** it fails with `usage.conflicting-options`, naming `troupe perform`, `--expect` and `--no-effect-check`

#### Scenario: A repeatable option given twice is not a conflict
- **WHEN** a person gives `--expect a.txt --expect b.txt` and no `--no-effect-check`
- **THEN** no `usage.conflicting-options` error is reported

#### Scenario: Too many positional values
- **WHEN** a person runs `troupe status one two`
- **THEN** it fails with `usage.extra-argument`, naming `troupe status` and `two`

#### Scenario: An option with no value at the end
- **WHEN** a person runs `troupe status --limit`
- **THEN** it fails with `usage.missing-value`, naming `troupe status` and `--limit`

#### Scenario: An option followed by another flag instead of its value
- **WHEN** a person runs `troupe status --limit --json`
- **THEN** it fails with `usage.missing-value`, naming `--limit`

#### Scenario: A value of the wrong type
- **WHEN** a person runs `troupe status --limit notanumber`
- **THEN** it fails with `usage.invalid-value`, naming `troupe status`, `--limit` and `notanumber`

#### Scenario: Values after `--` count as positionals
- **WHEN** a person runs `troupe status -- -5 -6`
- **THEN** it fails with `usage.extra-argument`, naming `-6`

### Requirement: An unanticipated usage problem is still reported as structured data
A usage problem the CLI's own checks do not recognise SHALL be reported as `usage.invalid`, exiting 2, with the
underlying message as its problem (with no surface prefix), the command in its details (or none, before a command is
chosen), and a fix pointing at the relevant help. It SHALL NOT fall through to a success or to another code.

#### Scenario: A parse failure the checks did not anticipate
- **WHEN** the argument parser reports a failure that is not one of the named usage shapes
- **THEN** the error is `usage.invalid`, exits 2, and validates against the protocol's error schema

### Requirement: Exit codes are defined in one place
Every exit code the CLI can return SHALL be defined in a single named table that the CLI and its documentation both
use. The CLI SHALL NOT return a code that is absent from that table.

#### Scenario: Every returned code is documented
- **WHEN** the CLI exits for any reason covered by the test suite
- **THEN** the exit code appears in the exit-code table

### Requirement: The theatre is found from the working directory
A command that needs a theatre SHALL use the nearest directory, from the working directory upwards, that contains
`.troupe/`. If there is none, it SHALL fail with `theatre.not-found`, naming the directory it searched from, and SHALL
NOT create one.

#### Scenario: Run from a subdirectory
- **WHEN** a person runs `troupe status` in `src/` of a project whose root holds `.troupe/`
- **THEN** the project's root is the theatre

#### Scenario: No theatre
- **WHEN** a person runs `troupe perform tester ...` in a directory with no `.troupe/` above it
- **THEN** it fails with `theatre.not-found`, naming that directory
- **AND** no `.troupe/` is created

### Requirement: Perform shows progress on standard error and the result on standard output
`troupe perform` SHALL write the run id at once, then each run event and notice as it happens, to standard error. On
success it SHALL write the run id and `succeeded` to standard output. Otherwise standard output SHALL stay empty, and
the run's error SHALL be shown on standard error with the run id.

#### Scenario: Progress while a run is going
- **WHEN** a run is going
- **THEN** standard error shows the run id before the first event, and a line for each event as it is recorded

#### Scenario: A failed run
- **WHEN** a run ends `failed`
- **THEN** standard output is empty
- **AND** standard error shows the run id, the problem and the fix

### Requirement: Perform's exit code follows the run's outcome
`troupe perform` SHALL exit 0 when the run `succeeded`, 130 when it was `cancelled`, and 1 for every other outcome. A
`perform` refused before the run starts SHALL exit with its error's code.

#### Scenario: Cancelled with Ctrl-C
- **WHEN** a person cancels a run with Ctrl-C
- **THEN** `troupe perform` exits 130, on Linux, macOS and Windows

#### Scenario: A crashed run
- **WHEN** a run ends `crashed`
- **THEN** `troupe perform` exits 1

### Requirement: Status and logs commands
`troupe status [<run>] [--limit <n>]` SHALL show runs, and `troupe logs <run> [--follow]` SHALL show a run's events,
each as the `status` and `logs` queries return them. Both SHALL show the store's notices on standard error.

#### Scenario: Logs from another terminal
- **WHEN** a person runs `troupe logs <run> --follow` in another terminal while the run is going
- **THEN** each event appears as it is recorded, and the command exits 0 when the run's end is recorded

### Requirement: Query results as JSON
`troupe status` and `troupe logs` SHALL take `--json`, which writes the query's result to standard output exactly in
its protocol shape. With `--follow`, each update SHALL be written as one line, then the result.

#### Scenario: Status as JSON
- **WHEN** a person runs `troupe status --json`
- **THEN** standard output is one JSON document that validates against the `status` result schema

### Requirement: Perform names an actor from config
`troupe perform <actor>` SHALL run the actor as config defines it, taking `--direction <text>` (optional) and
`--rehearse`, and no flag that names a runner, options or an effect check. An actor that isn't in config SHALL be
refused with `config.unknown-actor`, naming the actors config has.

#### Scenario: Perform from config
- **WHEN** config defines `tester` with the scripted runner, a script and `expect: ["out/hello.txt"]`, and a person
  runs `troupe perform tester --direction "write the hello file"`
- **THEN** the run uses that runner, script and effect check, with that direction

#### Scenario: An interim flag
- **WHEN** a person runs `troupe perform tester --runner scripted`
- **THEN** it exits with the usage-error code, naming `--runner` as unknown

#### Scenario: An actor that isn't configured
- **WHEN** a person runs `troupe perform nobody`
- **THEN** it fails with `config.unknown-actor`, naming the actors config has

### Requirement: Every command that changes anything can be rehearsed
Every command that records events or writes files SHALL take `--rehearse` (#137). A rehearsal SHALL run the command's
checks, show what the command would record, write or start, and record nothing, write nothing and start nothing.

#### Scenario: Rehearsing a config change
- **WHEN** a person runs `troupe config set actors.tester.runner=claude-code --rehearse`
- **THEN** it shows the change it would record and the files it would write
- **AND** no event is recorded and no file is written

#### Scenario: Rehearsing a perform
- **WHEN** a person runs `troupe perform tester --rehearse`
- **THEN** it shows the actor, runner, stage and effect check it would run, and the character and direction by hash
  and length
- **AND** no runner is started and no event is recorded

### Requirement: A rehearsal's exit code says what it found
A rehearsal SHALL exit 0 when the command would succeed with nothing to do, with the exit code for "would change"
when it would succeed and change something, and with the refusal's own code when it would be refused.

#### Scenario: Files that are out of date
- **WHEN** a person runs `troupe flush --rehearse` and a config file isn't what config would write
- **THEN** it exits with the "would change" code, naming the file

#### Scenario: Files in line
- **WHEN** every config file is what config would write
- **THEN** `troupe flush --rehearse` exits 0

#### Scenario: A rehearsal that would be refused
- **WHEN** a config file was edited by hand and a person runs `troupe flush --rehearse`
- **THEN** it exits with the code of `config.file-not-troupes`, naming the file

### Requirement: Config and flush commands
The CLI SHALL offer `troupe config set`, `troupe config unset`, `troupe config get` and `troupe flush`, each calling
the core through the client protocol. `troupe config get` SHALL take `--json`, which writes the query's result
exactly in its protocol shape.

#### Scenario: Config get as JSON
- **WHEN** a person runs `troupe config get --json`
- **THEN** standard output is one JSON document that validates against the `config-get` result schema

### Requirement: Diff, accept and discard commands
The CLI SHALL offer `troupe diff <run>`, `troupe accept <run>` and `troupe discard <run>`, each calling the core
through the client protocol and naming the run by id or unique prefix. `troupe diff` SHALL write the diff to standard
output exactly as captured, and SHALL take `--json`. `troupe accept` and `troupe discard` SHALL take `--reason` and
`--rehearse`.

#### Scenario: A diff to pipe
- **WHEN** a person runs `troupe diff <run>` for a run with pending changes
- **THEN** standard output is the captured diff byte for byte, and `git apply --check` accepts it at the base commit

#### Scenario: A diff as JSON
- **WHEN** a person runs `troupe diff <run> --json`
- **THEN** standard output is one JSON document that validates against the `diff` result schema

#### Scenario: Accept
- **WHEN** a person runs `troupe accept <run> --reason "looks right"`
- **THEN** the run's changes are in the working tree, and standard output names the run and the files changed

#### Scenario: Rehearsing an accept
- **WHEN** a person runs `troupe accept <run> --rehearse` and the diff applies cleanly
- **THEN** it exits with the "would change" code and names the files it would change, and nothing changes

#### Scenario: A conflicting accept
- **WHEN** a person runs `troupe accept <run>` and the diff doesn't apply cleanly
- **THEN** it exits non-zero with `run.changes-conflict`, and standard error names the files, the diff's reference,
  the worktree's path, and how to look at the diff with `troupe diff`

### Requirement: Perform says where a worktree run works
`troupe perform` SHALL show, on standard error before the first event, the workspace of a worktree run with its
path. A rehearsal SHALL show the workspace it would use. When a worktree run's changes are pending at its end, the CLI
SHALL say how to see, accept or discard them.

#### Scenario: The end of a worktree run
- **WHEN** a worktree run ends with changes
- **THEN** standard error names the worktree and the commands `troupe diff`, `troupe accept` and `troupe discard` for
  the run

#### Scenario: Rehearsing a worktree perform
- **WHEN** a person runs `troupe perform tester --rehearse` for an actor whose workspace is `worktree`
- **THEN** it shows workspace `worktree` and the base commit it would use
- **AND** no worktree is made
