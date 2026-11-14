## MODIFIED Requirements

### Requirement: The install check can install from GitHub by a ref
The install check SHALL, when asked, install from troupe's GitHub repository with the ref exactly as given, in the
documented form for that ref, and then with `all` if that ref's bundle has it. For a `troupe-run-v<version>` tag,
`troupe-run` SHALL declare that version at the tag, every component in its dependencies and its extras SHALL be pinned,
and `troupe --version` SHALL print the version `troupe` is pinned at; otherwise the check fails, naming the tag and what
differed.

#### Scenario: A release tag from GitHub
- **WHEN** the install check runs from GitHub with `troupe-run-v0.1.0` as the ref, and the bundle pins `troupe-v0.1.0`
- **THEN** it installs with `uv tool install --no-sources
  "git+https://github.com/troupe-run/troupe@troupe-run-v0.1.0#subdirectory=packages/troupe-run"`, and
  `troupe --version` names troupe 0.1.0
- **AND** it installs with `uv tool install --no-sources
  "troupe-run[all] @ git+https://github.com/troupe-run/troupe@troupe-run-v0.1.0#subdirectory=packages/troupe-run"`
  into a tool directory of its own

#### Scenario: A bundle version and a core version that differ
- **WHEN** the install check runs with `troupe-run-v0.2.0` as the ref, and the bundle pins `troupe-v0.1.3`
- **THEN** it expects `troupe --version` to name troupe 0.1.3, and passes when it does

#### Scenario: A tag whose version troupe doesn't print
- **WHEN** the installed `troupe --version` names a version other than the one `troupe` is pinned at in the tag
- **THEN** the install check fails, naming the tag, the pinned version and what `troupe --version` printed

#### Scenario: A tag with a component that isn't pinned
- **WHEN** the install check runs with a `troupe-run-v<version>` tag whose bundle names `troupe-stage-local` bare
- **THEN** it fails before installing, naming the tag and `troupe-stage-local`, since `--no-sources` would look for it
  on a package index

#### Scenario: A tag with an extra's runner that isn't pinned
- **WHEN** the install check runs with a `troupe-run-v<version>` tag whose `example` extra names
  `troupe-runner-example` bare
- **THEN** it fails before installing, naming the tag, the extra and `troupe-runner-example`

#### Scenario: A tag from before the all extra
- **WHEN** the install check runs from GitHub with `troupe-run-v0.1.0` as the ref, whose bundle has no `all` extra
- **THEN** it installs and checks the base install, says it doesn't install `troupe-run[all]` for that ref, and passes

### Requirement: A runner with dependencies beyond the SDK is an extra named after it
A plugin under `plugins/` that depends on anything besides `troupe-plugin-sdk` SHALL be in `troupe-run`'s optional
dependencies under an extra named exactly as troupe's runner table names its runner, and SHALL NOT be in the base
dependencies. A plugin whose only dependency is the SDK SHALL NOT have an extra. The check SHALL fail otherwise,
naming the plugin, the file and where it belongs.

#### Scenario: A library-backed runner in the base dependencies
- **WHEN** `plugins/runner-example/pyproject.toml` depends on a client library, `example-sdk`, and
  `troupe-runner-example` is in `troupe-run`'s base dependencies
- **THEN** `scripts/check.py` fails, naming `troupe-runner-example`, `packages/troupe-run/pyproject.toml` and the
  extra `example`

#### Scenario: A library-backed runner in its extra
- **WHEN** the same plugin is only in `troupe-run`'s `example` extra, and troupe's runner table names its runner
  `example`
- **THEN** the bundle check passes

#### Scenario: An extra named after the library
- **WHEN** the plugin is in an extra named `example-sdk` while troupe's runner table names its runner `example`
- **THEN** `scripts/check.py` fails, naming the extra, the runner's name and the file

#### Scenario: An SDK-only runner given an extra
- **WHEN** `troupe-run` has an extra `scripted` and `plugins/runner-scripted` depends only on the SDK
- **THEN** `scripts/check.py` fails, naming `scripted` and saying the runner belongs in the base dependencies

### Requirement: The all extra installs every runner
`troupe-run` SHALL have an extra named `all` that names every plugin in every other extra, each exactly as that extra
names it, and nothing else. Its only other extras SHALL be the runners'. The check SHALL fail otherwise, naming the
extra, the difference and the file.

#### Scenario: No runner has an extra yet
- **WHEN** every plugin depends only on the SDK
- **THEN** `troupe-run`'s `all` extra is empty, and the bundle check passes

#### Scenario: A runner left out of all
- **WHEN** `troupe-run` has an `example` extra and its `all` extra doesn't name `troupe-runner-example`
- **THEN** `scripts/check.py` fails, naming `all`, `troupe-runner-example` and `packages/troupe-run/pyproject.toml`

#### Scenario: All pins another version
- **WHEN** the `example` extra pins `troupe-runner-example-v0.1.1` and `all` pins `troupe-runner-example-v0.1.0`
- **THEN** `scripts/check.py` fails, naming both references

#### Scenario: An extra that isn't a runner's
- **WHEN** `troupe-run` has an extra `dev`
- **THEN** `scripts/check.py` fails, naming `dev` and saying `troupe-run`'s extras are its runners' and `all`

### Requirement: The base install refuses each extra's runner by its extra
After installing `troupe-run` without extras, the install check SHALL rehearse an audition (`troupe init --audition
--runner <runner> --rehearse`) for each runner that has an extra, and SHALL expect it to be refused, naming
`troupe-run[<extra>]`. Any other outcome SHALL fail the check, naming the runner and what happened.

#### Scenario: The refusal names the extra
- **WHEN** `troupe-run` has an `example` extra and the base install rehearses an audition on `example`
- **THEN** it is refused, its fix naming `troupe-run[example]`, and the install check passes

#### Scenario: No runner has an extra yet
- **WHEN** `troupe-run` has no runner extras
- **THEN** the base install rehearses no such audition, and the install check passes

### Requirement: The install page lists each runner's extra
The install page SHALL say that runners with client libraries come as extras, give the extras form of the command, and
list each extra with its runner, exactly the extras `troupe-run` has. A list that differs SHALL fail the docs check,
naming the page and each extra missing or extra.

#### Scenario: A new extra not on the page
- **WHEN** `troupe-run` has an `example` extra and the install page's list doesn't name it
- **THEN** the docs check fails, naming `docs/opening-night/install.md` and `example`

#### Scenario: No runner has an extra yet
- **WHEN** `troupe-run` has only the `all` extra
- **THEN** the page's list names only `all`, and the docs check passes
