# installation Specification

## Purpose

Capability: `cap:development`, `cap:user-docs`

How someone outside this repository installs troupe with uv: the bundle package that brings core, its adapters and its
runners together, the one documented install command, and the check that runs that command on every platform.

## Requirements

### Requirement: One package installs troupe with everything it bundles
The `troupe-run` package SHALL depend on `troupe`, on every other package under `packages/` and on every plugin under
`plugins/` whose only dependency is the plugin SDK, each bare or pinned at a release tag; every other plugin is in its
runner's extra. A workspace member in neither SHALL fail the repository's check, naming it and the file to add it to. An
install from a commit SHALL take each one asked for from that commit, and a bundle tag installed the documented way,
each from its pin.

#### Scenario: A new adapter that the bundle leaves out
- **WHEN** a package is added under `packages/` and not to `troupe-run`'s dependencies
- **THEN** `scripts/check.py` fails, naming the package and `packages/troupe-run/pyproject.toml`

#### Scenario: Installed from one commit
- **WHEN** `troupe-run` is installed with uv from a commit of this repository, without `--no-sources`
- **THEN** troupe, each adapter and each runner plugin installed is the one in that commit's tree, whatever the pins say

#### Scenario: Installed from a bundle tag
- **WHEN** `troupe-run-v0.1.1` pins `troupe-vcs-git-v0.1.1` and `troupe-v0.1.0`, and is installed with `--no-sources`
- **THEN** `troupe-vcs-git` is installed from the `troupe-vcs-git-v0.1.1` tree and `troupe` from the `troupe-v0.1.0`
  tree, including where another component depends on `troupe`

#### Scenario: An SDK-only runner is in the base install
- **WHEN** `plugins/runner-scripted/pyproject.toml` depends only on `troupe-plugin-sdk`
- **THEN** the bundle check passes only when `troupe-runner-scripted` is in `troupe-run`'s dependencies

### Requirement: Core declares no dependency only for distribution
The `troupe` package's dependencies SHALL NOT name any other workspace member except `troupe-plugin-sdk`, whose
runner contract types core uses. Only `troupe-run` brings the adapters and plugins into an install. A core dependency
on any other workspace member SHALL fail the repository's check, naming it.

#### Scenario: Core depends on an adapter
- **WHEN** `packages/troupe/pyproject.toml` lists `troupe-vcs-git` as a dependency
- **THEN** `scripts/check.py` fails, naming `troupe-vcs-git`, the file, and `troupe-run` as where it belongs

#### Scenario: Core depends on the plugin SDK
- **WHEN** `packages/troupe/pyproject.toml` lists `troupe-plugin-sdk`, bare
- **THEN** the bundle check passes

### Requirement: The bundle provides the troupe command
Installing `troupe-run` as a uv tool SHALL put a `troupe` command on the person's path that runs exactly what core's
own `troupe` command runs. The check SHALL fail when the bundle's `troupe` command differs from core's, naming both.

#### Scenario: Installed as a tool
- **WHEN** someone runs the documented install command
- **THEN** `troupe --version` prints the installed troupe version and the protocol version it carries

#### Scenario: The command points somewhere else
- **WHEN** `troupe-run` declares a `troupe` command whose target isn't the one `troupe` declares
- **THEN** `scripts/check.py` fails, naming both targets

### Requirement: The install command is documented in one form
The README and the user docs' install page SHALL give the install command, with the ref named, and the Python versions
troupe needs. Every copy SHALL match the form the install check runs for its ref: the plain form for `main` or a commit
placeholder, the `--no-sources` form for the bundle's release tag, and with extras, `troupe-run[<extras>] @ ` before the
URL. A copy that differs SHALL fail the docs check, naming the page, the line and the expected command.

#### Scenario: The page and the check agree
- **WHEN** the manifest gives `packages/troupe-run` 0.1.0 and the install page's command is the form the install
  check runs, with `troupe-run-v0.1.0` as the ref
- **THEN** the docs check passes

#### Scenario: A page names another subdirectory
- **WHEN** the README's install command says `#subdirectory=packages/troupe`
- **THEN** the docs check fails, naming `README.md`, the line and the expected command

#### Scenario: A page names core's tag
- **WHEN** the README's install command names `@troupe-v0.1.0`
- **THEN** the docs check fails, naming `README.md`, the line and the expected command

#### Scenario: A tag without --no-sources
- **WHEN** the manifest gives `packages/troupe-run` 0.1.0 and the install page's command names `@troupe-run-v0.1.0`
  without `--no-sources`
- **THEN** the docs check fails, naming `docs/opening-night/install.md`, the line and the command with `--no-sources`

#### Scenario: The Python versions
- **WHEN** someone reads the install page
- **THEN** it says troupe needs Python 3.12 to 3.15, the bound every `pyproject.toml` declares, and that uv provides it

#### Scenario: The extras form
- **WHEN** the manifest gives `packages/troupe-run` 0.1.0 and the install page gives `uv tool install --no-sources
  "troupe-run[all] @ git+https://github.com/troupe-run/troupe@troupe-run-v0.1.0#subdirectory=packages/troupe-run"`
- **THEN** the docs check passes

#### Scenario: An extra the bundle doesn't have
- **WHEN** the install page's command names `troupe-run[gemini]` and `troupe-run` has no extra `gemini`
- **THEN** the docs check fails, naming the page, the line, `gemini` and the extras `troupe-run` has

### Requirement: The documented install is checked on every platform
The install check SHALL run the documented command against a given commit, into a tool directory of its own, on a given
Python, then the installed `troupe --version` and a scripted performance in a new theatre outside the checkout. It SHALL
then install `troupe-run[all]` into another tool directory and rehearse an audition on every runner troupe knows, each
succeeding. CI SHALL run it against the commit under test on Linux, macOS and Windows, on every supported Python.

#### Scenario: The commit under test
- **WHEN** CI runs the full check on a pull request
- **THEN** each platform and Python leg installs `troupe-run` from that commit and a scripted performance succeeds
- **AND** the same leg installs `troupe-run[all]` from that commit

#### Scenario: An install that can't run an actor
- **WHEN** the installed troupe can't start the scripted runner
- **THEN** the install check fails, naming the step that failed and its output

#### Scenario: The person's own tools are untouched
- **WHEN** a developer runs the install check on their own machine
- **THEN** it installs nothing into their uv tool directory or onto their path, and removes what it installed

#### Scenario: An extra whose library has no wheel for a platform
- **WHEN** a runner's extra depends on a compiled library with no wheel, and no way to build one, for Windows on
  Python 3.15
- **THEN** the Windows, Python 3.15 leg fails at the `troupe-run[all]` install, naming the step and uv's output

#### Scenario: A runner missing from the all install
- **WHEN** `troupe-run[all]` is installed and rehearsing an audition on one of the runners troupe knows is refused
- **THEN** the install check fails, naming the runner, the step and its output

### Requirement: A documented tag is the bundle's current release
A copy of the install command that names a tag SHALL name the bundle's tag, `troupe-run-v<version>`, where `<version>`
is `troupe-run`'s version in the release manifest. A copy naming any other version SHALL fail the docs check, naming
the page, the line and the version expected. Before the first release the manifest says 0.0.0, so no copy can name a
tag yet.

#### Scenario: The bundle's tag at its released version
- **WHEN** the manifest gives `packages/troupe-run` 0.1.0 and the install page's command names `@troupe-run-v0.1.0`
- **THEN** the docs check passes

#### Scenario: A tag that doesn't exist yet
- **WHEN** the manifest gives `packages/troupe-run` 0.0.0 and the README's command names `@troupe-run-v0.1.0`
- **THEN** the docs check fails, naming `README.md`, the line and version 0.0.0

### Requirement: The install pages name the release once there is one
Once the release manifest gives `troupe-run` a released version, the README and the install page SHALL give the
install command with the bundle's tag at that version, not `main`. A copy on either page naming `main` SHALL then fail
the docs check, naming the page, the line and the tag command to give. Other pages, which no release moves, MAY still
give `main` or a commit.

#### Scenario: The README goes back to main after a release
- **WHEN** the manifest gives `packages/troupe-run` 0.1.0 and the README's command names `@main`
- **THEN** the docs check fails, naming `README.md`, the line and the command with `@troupe-run-v0.1.0` and
  `--no-sources`

#### Scenario: Before the first release
- **WHEN** the manifest gives `packages/troupe-run` 0.0.0 and the install page's command names `@main`
- **THEN** the docs check passes

#### Scenario: A page no release moves
- **WHEN** the manifest gives `packages/troupe-run` 0.1.0 and `packages/troupe-run/README.md` gives the command with
  `@main`
- **THEN** the docs check passes

### Requirement: Each release moves the documented tag
The README and the install page SHALL hold their install command between release-please's version markers, and the
bundle's release configuration SHALL update both files. A release pull request SHALL then change a documented
`troupe-run-v<version>` to the new version, in the same commit as the manifest. A copy naming `main` or a tag outside
the markers SHALL fail the docs check, naming the page and the line.

#### Scenario: A release pull request
- **WHEN** a release pull request releases `troupe-run` at 0.2.0 and the README's command names `@troupe-run-v0.1.0`
- **THEN** the pull request changes it to `@troupe-run-v0.2.0`, and the docs check passes on it

#### Scenario: A command outside the markers
- **WHEN** the install page gives the command after the markers' end
- **THEN** the docs check fails, naming `docs/opening-night/install.md` and the line

#### Scenario: Before the first tag
- **WHEN** a release pull request releases `troupe-run` while the README's command names `@main`
- **THEN** the command is unchanged

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
- **WHEN** the install check runs with a `troupe-run-v<version>` tag whose `lm-studio` extra names
  `troupe-runner-lm-studio` bare
- **THEN** it fails before installing, naming the tag, the extra and `troupe-runner-lm-studio`

#### Scenario: A tag from before the all extra
- **WHEN** the install check runs from GitHub with `troupe-run-v0.1.0` as the ref, whose bundle has no `all` extra
- **THEN** it installs and checks the base install, says it doesn't install `troupe-run[all]` for that ref, and passes

### Requirement: Every published bundle tag is checked on every platform
When a GitHub release is published for a `troupe-run-v<version>` tag, a workflow SHALL run the install check from
GitHub against that tag on Linux, macOS and Windows, on every supported Python, including a scripted performance with
the installed `troupe`. Its Python matrix SHALL be the supported versions, or the repository's check fails, naming the
workflow. It SHALL also run on demand for a given ref.

#### Scenario: A release is published
- **WHEN** release-please publishes releases for `troupe-v0.1.0`, `troupe-run-v0.1.0` and `protocol-v0.1.0`
- **THEN** the workflow checks `troupe-run-v0.1.0` on each platform and Python, and does nothing for the other two

#### Scenario: The matrix leaves out a supported Python
- **WHEN** the supported versions are 3.12 to 3.15 and the workflow's matrix lists only 3.12 to 3.14
- **THEN** `scripts/check.py` fails, naming the workflow and the missing 3.15

### Requirement: A failed check on a published tag opens a Bug
When the release install check fails for a tag, the workflow SHALL open one Bug issue in troupe-run/troupe naming the
tag, each failed platform and Python, and the run, or comment on that tag's Bug if one is open. It SHALL NOT move, delete or edit the tag or its release. Its token
SHALL be able to read the repository and its runs and write issues, and nothing else.

#### Scenario: Windows fails for a published tag
- **WHEN** the check for `troupe-run-v0.1.0` fails on Windows with Python 3.15 and passes everywhere else
- **THEN** one Bug issue is opened naming `troupe-run-v0.1.0`, Windows, Python 3.15 and the run, and the tag and
  release are unchanged

#### Scenario: Every leg passes
- **WHEN** the check passes on every platform and Python
- **THEN** no issue is opened

#### Scenario: A re-run fails while the tag's Bug is open
- **WHEN** the check for `troupe-run-v0.1.0` is run again on demand and fails, and its Bug is still open
- **THEN** no second issue is opened, and the open Bug gets a comment naming the failed legs and the new run

### Requirement: A pinned component's released workspace dependencies are pinned too
When the bundle pins a component that depends on another workspace member that has released, the bundle SHALL pin
that member too, so an install of the bundle's tag never looks it up on a package index. The check SHALL fail
otherwise, naming both and the file.

#### Scenario: Core pinned, the released SDK bare
- **WHEN** `troupe-run` pins `troupe`, core depends on the SDK, the manifest gives the SDK 0.1.0, and `troupe-run`
  names `troupe-plugin-sdk` bare
- **THEN** `scripts/check.py` fails, naming `troupe-plugin-sdk`, `troupe` and `packages/troupe-run/pyproject.toml`

#### Scenario: The SDK not yet released
- **WHEN** `troupe-run` pins `troupe` and names `troupe-plugin-sdk` bare, and the manifest gives the SDK 0.0.0
- **THEN** the check passes

### Requirement: A runner with dependencies beyond the SDK is an extra named after it
A plugin under `plugins/` that depends on anything besides `troupe-plugin-sdk` SHALL be in `troupe-run`'s optional
dependencies under an extra named exactly as troupe's runner table names its runner, and SHALL NOT be in the base
dependencies. A plugin whose only dependency is the SDK SHALL NOT have an extra. The check SHALL fail otherwise,
naming the plugin, the file and where it belongs.

#### Scenario: A library-backed runner in the base dependencies
- **WHEN** `plugins/runner-lm-studio/pyproject.toml` depends on `lmstudio` and `troupe-runner-lm-studio` is in
  `troupe-run`'s base dependencies
- **THEN** `scripts/check.py` fails, naming `troupe-runner-lm-studio`, `packages/troupe-run/pyproject.toml` and the
  extra `lm-studio`

#### Scenario: A library-backed runner in its extra
- **WHEN** the same plugin is only in `troupe-run`'s `lm-studio` extra, and troupe's runner table names its runner
  `lm-studio`
- **THEN** the bundle check passes

#### Scenario: An extra named after the library
- **WHEN** the plugin is in an extra named `lmstudio` while troupe's runner table names its runner `lm-studio`
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
- **WHEN** `troupe-run` has an `lm-studio` extra and its `all` extra doesn't name `troupe-runner-lm-studio`
- **THEN** `scripts/check.py` fails, naming `all`, `troupe-runner-lm-studio` and `packages/troupe-run/pyproject.toml`

#### Scenario: All pins another version
- **WHEN** the `lm-studio` extra pins `troupe-runner-lm-studio-v0.1.1` and `all` pins `troupe-runner-lm-studio-v0.1.0`
- **THEN** `scripts/check.py` fails, naming both references

#### Scenario: An extra that isn't a runner's
- **WHEN** `troupe-run` has an extra `dev`
- **THEN** `scripts/check.py` fails, naming `dev` and saying `troupe-run`'s extras are its runners' and `all`

### Requirement: The base install refuses each extra's runner by its extra
After installing `troupe-run` without extras, the install check SHALL rehearse an audition (`troupe init --audition
--runner <runner> --rehearse`) for each runner that has an extra, and SHALL expect it to be refused, naming
`troupe-run[<extra>]`. Any other outcome SHALL fail the check, naming the runner and what happened.

#### Scenario: The refusal names the extra
- **WHEN** `troupe-run` has an `lm-studio` extra and the base install rehearses an audition on `lm-studio`
- **THEN** it is refused, its fix naming `troupe-run[lm-studio]`, and the install check passes

#### Scenario: No runner has an extra yet
- **WHEN** `troupe-run` has no runner extras
- **THEN** the base install rehearses no such audition, and the install check passes

### Requirement: The install page lists each runner's extra
The install page SHALL say that runners with client libraries come as extras, give the extras form of the command, and
list each extra with its runner, exactly the extras `troupe-run` has. A list that differs SHALL fail the docs check,
naming the page and each extra missing or extra.

#### Scenario: A new extra not on the page
- **WHEN** `troupe-run` has an `lm-studio` extra and the install page's list doesn't name it
- **THEN** the docs check fails, naming `docs/opening-night/install.md` and `lm-studio`

#### Scenario: No runner has an extra yet
- **WHEN** `troupe-run` has only the `all` extra
- **THEN** the page's list names only `all`, and the docs check passes

### Requirement: The install check outlasts a short network outage
The install check SHALL retry a failed connection to a package index for longer than uv does by default, with the
number of retries named in one place, so a short outage on one runner doesn't fail it. A failure that isn't a network
fault, such as a package the index doesn't have, SHALL still fail it without waiting, naming the step and uv's output.

#### Scenario: An index that fails more often than uv's default retries allow
- **WHEN** the package index answers the install's first four requests to it with an error a retry can recover from,
  then serves them
- **THEN** the install succeeds

#### Scenario: A package that doesn't resolve
- **WHEN** a requirement names a package the index doesn't have
- **THEN** the install fails after the index's one answer for that package, without asking again, naming the install
  step and uv's output

#### Scenario: An outage longer than the retries allow
- **WHEN** the package index fails every request for longer than the retries can outlast
- **THEN** the install fails, naming the install step and uv's output

### Requirement: The caller's own retry setting is kept
When whoever runs the install check has set uv's retry count in the environment, the check SHALL pass that value to uv
unchanged rather than its own. A value uv can't read SHALL fail the install step, naming the variable and the value,
not fall back to the check's own.

#### Scenario: A retry count set by the caller
- **WHEN** the install check runs with `UV_HTTP_RETRIES=1` in its environment
- **THEN** each `uv tool install` it runs gets `UV_HTTP_RETRIES=1`

#### Scenario: A malformed retry count
- **WHEN** the install check runs with `UV_HTTP_RETRIES=abc` in its environment
- **THEN** the install check fails at the install step, and its output names `UV_HTTP_RETRIES` and `abc`
