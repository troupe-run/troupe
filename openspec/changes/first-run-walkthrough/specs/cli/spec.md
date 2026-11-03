## MODIFIED Requirements

### Requirement: Init prints the next steps for its audition
After an audition, `troupe init` SHALL print, in order: committing `.troupe/`, allowing the local stage when policy
doesn't already allow it, and `troupe perform lead` with an example `--direction`. For Claude Code it SHALL say that
Claude Code must be installed and logged in. The allow step SHALL say to add its line to the shell profile once, naming
the profile for the platform, so that it applies to every theatre the person runs.

#### Scenario: Next steps when policy doesn't allow the local stage
- **WHEN** a person runs `troupe init --audition` with `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE` unset
- **THEN** standard output shows a `git add .troupe` and `git commit` step, then the step that sets
  `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true`, then `troupe perform lead --direction "..."`

#### Scenario: Next steps when policy already allows it
- **WHEN** a person runs `troupe init --audition` with `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true`
- **THEN** standard output shows the commit step and the perform step, and no policy step

#### Scenario: The allow step says to set it once, in the shell profile
- **WHEN** a person on Linux or macOS runs `troupe init --audition` with `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE`
  unset
- **THEN** the allow step's note names `~/.zshrc` and `~/.bashrc`, says to add the line once, and that it then applies
  to every theatre
- **AND** it doesn't say to set it in each shell

#### Scenario: The allow step on Windows names the PowerShell profile
- **WHEN** a person on Windows runs `troupe init --audition` with `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE` unset
- **THEN** the allow step's line is the `$env:` form, and its note names the PowerShell profile (`$PROFILE`)

#### Scenario: The printed steps work in an empty repository
- **WHEN** a person runs `troupe init --audition --runner scripted` in an empty git repository, then each printed
  step in order, offline
- **THEN** the `troupe perform` it printed ends `succeeded` and exits 0

#### Scenario: The printed steps work with Claude Code
- **WHEN** a person with Claude Code installed and logged in runs `troupe init --audition` in an empty git
  repository, then each printed step in order
- **THEN** the `troupe perform` it printed ends `succeeded` and exits 0
