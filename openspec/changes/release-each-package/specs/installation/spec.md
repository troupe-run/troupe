## MODIFIED Requirements

### Requirement: One package installs troupe with everything it bundles
The `troupe-run` package SHALL depend on `troupe`, on every other package under `packages/` and on every plugin under
`plugins/`, each bare or pinned at a release tag. A workspace member missing from those dependencies SHALL fail the
repository's check, naming the member and the file to add it to. Installing `troupe-run` from a commit SHALL install
every one of them from that commit; installing a bundle tag the documented way SHALL install each from its pin.

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

### Requirement: The install command is documented in one form
The README and the user docs' install page SHALL give the install command, with the ref to install named, and the
Python versions troupe needs. Every copy SHALL match the form the install check runs for its ref: with `main` or a
commit placeholder, the plain form; with the bundle's release tag, the form with `--no-sources`. A copy that differs
SHALL fail the docs check, naming the page, the line and the expected command.

#### Scenario: The page and the check agree
- **WHEN** the install page's command is the form the install check runs, with `main` as the ref
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

### Requirement: The install check can install from GitHub by a ref
The install check SHALL, when asked, install from troupe's GitHub repository with the ref exactly as given, in the
documented form for that ref. For a `troupe-run-v<version>` tag, `troupe-run` SHALL declare that version at the tag,
every component SHALL be pinned, and `troupe --version` SHALL print the version `troupe` is pinned at; otherwise the
check fails, naming the tag and what differed.

#### Scenario: A release tag from GitHub
- **WHEN** the install check runs from GitHub with `troupe-run-v0.1.0` as the ref, and the bundle pins `troupe-v0.1.0`
- **THEN** it installs with `uv tool install --no-sources
  "git+https://github.com/troupe-run/troupe@troupe-run-v0.1.0#subdirectory=packages/troupe-run"`, and
  `troupe --version` names troupe 0.1.0

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
