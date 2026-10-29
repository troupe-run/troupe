# Spec Delta

## Purpose

Capability: `cap:development`, `cap:user-docs`

How someone outside this repository installs troupe with uv: the bundle package that brings core, its adapters and its
runners together, the one documented install command, and the check that runs that command on every platform.

## ADDED Requirements

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
Python versions troupe needs. Every copy of the command SHALL match the one form the install check runs. A copy that
differs SHALL fail the docs check, naming the page, the line and the expected command.

#### Scenario: The page and the check agree
- **WHEN** the install page's command is the form the install check runs, with `main` as the ref
- **THEN** the docs check passes

#### Scenario: A page names another subdirectory
- **WHEN** the README's install command says `#subdirectory=packages/troupe`
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
