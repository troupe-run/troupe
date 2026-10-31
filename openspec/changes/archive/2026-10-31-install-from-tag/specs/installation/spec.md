# Spec Delta

## MODIFIED Requirements

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

## ADDED Requirements

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
