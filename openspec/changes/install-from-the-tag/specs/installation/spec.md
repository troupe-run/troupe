## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: The install command is documented in one form
The README and the user docs' install page SHALL give the install command, with the ref to install named, and the
Python versions troupe needs. Every copy SHALL match the form the install check runs for its ref: with `main` or a
commit placeholder, the plain form; with the bundle's release tag, the form with `--no-sources`. A copy that differs
SHALL fail the docs check, naming the page, the line and the expected command.

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
