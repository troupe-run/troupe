# installation Specification

## Purpose

Capability: `cap:development`, `cap:user-docs`

How someone outside this repository installs troupe with uv: the bundle package that brings core, its adapters and its
runners together, the one documented install command, and the check that runs that command on every platform.

## Requirements

### Requirement: One package installs troupe with everything it bundles
The `troupe-run` package SHALL depend on `troupe`, on every other package under `packages/` and on every plugin under
`plugins/`. A workspace member missing from those dependencies SHALL fail the repository's check, naming the member and
the file to add it to. Installing `troupe-run` from a commit SHALL install every one of them from that same commit.

#### Scenario: A new adapter that the bundle leaves out
- **WHEN** a package is added under `packages/` and not to `troupe-run`'s dependencies
- **THEN** `scripts/check.py` fails, naming the package and `packages/troupe-run/pyproject.toml`

#### Scenario: Installed from one commit
- **WHEN** `troupe-run` is installed with uv from a commit of this repository
- **THEN** troupe, each adapter and each runner plugin installed is the one in that commit's tree

### Requirement: Core declares no dependency only for distribution
The `troupe` package's dependencies SHALL NOT name any other workspace member. Only `troupe-run` brings the adapters
and plugins into an install. A core dependency on a workspace member SHALL fail the repository's check, naming it.

#### Scenario: Core depends on an adapter
- **WHEN** `packages/troupe/pyproject.toml` lists `troupe-vcs-git` as a dependency
- **THEN** `scripts/check.py` fails, naming `troupe-vcs-git`, the file, and `troupe-run` as where it belongs

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
The README and the user docs' install page SHALL give the install command, with the ref to install named, and the
Python versions troupe needs. Every copy of the command SHALL match the one form the install check runs, with `main`,
a commit placeholder or the bundle's release tag as the ref. A copy that differs SHALL fail the docs check, naming the
page, the line and the expected command.

#### Scenario: The page and the check agree
- **WHEN** the install page's command is the form the install check runs, with `main` as the ref
- **THEN** the docs check passes

#### Scenario: A page names another subdirectory
- **WHEN** the README's install command says `#subdirectory=packages/troupe`
- **THEN** the docs check fails, naming `README.md`, the line and the expected command

#### Scenario: A page names core's tag
- **WHEN** the README's install command names `@troupe-v0.1.0`
- **THEN** the docs check fails, naming `README.md`, the line and the expected command

#### Scenario: The Python versions
- **WHEN** someone reads the install page
- **THEN** it says troupe needs Python 3.12 to 3.15, the bound every `pyproject.toml` declares, and that uv provides it

### Requirement: The documented install is checked on every platform
The install check SHALL run the documented command against a given commit, into a tool directory of its own, on a given
Python, then run the installed `troupe`: `--version`, and a scripted performance in a new theatre outside the checkout.
CI SHALL run it against the commit under test on Linux, macOS and Windows, on every supported Python.

#### Scenario: The commit under test
- **WHEN** CI runs the full check on a pull request
- **THEN** each platform and Python leg installs `troupe-run` from that commit and a scripted performance succeeds

#### Scenario: An install that can't run an actor
- **WHEN** the installed troupe can't start the scripted runner
- **THEN** the install check fails, naming the step that failed and its output

#### Scenario: The person's own tools are untouched
- **WHEN** a developer runs the install check on their own machine
- **THEN** it installs nothing into their uv tool directory or onto their path, and removes what it installed

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
The install check SHALL, when asked, install from troupe's GitHub repository with the ref exactly as given, as the
documented command does, rather than from the checkout by commit. When the ref is a `troupe-run-v<version>` tag, the
installed `troupe --version` SHALL print that version, or the check fails naming the tag and what was printed.

#### Scenario: A release tag from GitHub
- **WHEN** the install check runs from GitHub with `troupe-run-v0.1.0` as the ref
- **THEN** it installs `git+https://github.com/troupe-run/troupe@troupe-run-v0.1.0#subdirectory=packages/troupe-run`,
  and `troupe --version` names troupe 0.1.0

#### Scenario: A tag whose version troupe doesn't print
- **WHEN** the installed `troupe --version` names a version other than the one in the `troupe-run-v<version>` tag
- **THEN** the install check fails, naming the tag and what `troupe --version` printed

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
