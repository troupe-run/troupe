## MODIFIED Requirements

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

### Requirement: The install check can install from GitHub by a ref
The install check SHALL, when asked, install from troupe's GitHub repository with the ref exactly as given, in the
documented form for that ref, both without extras and with `all`. For a `troupe-run-v<version>` tag, `troupe-run`
SHALL declare that version at the tag, every component in its dependencies and its extras SHALL be pinned, and
`troupe --version` SHALL print the version `troupe` is pinned at; otherwise the check fails, naming the tag and what
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

## ADDED Requirements

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
