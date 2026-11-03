## MODIFIED Requirements

### Requirement: Init with an audition defines a working example actor
`troupe init --audition` SHALL make the theatre as `troupe init` does, and SHALL define the example actor `lead` in
the same command. On success it SHALL print the actor, its runner, the files written, and the next steps. When the
actor has a character, it SHALL say how to change it with `troupe config set`, and SHALL NOT say to edit the file.

#### Scenario: An audition with the default runner
- **WHEN** a person runs `troupe init --audition` in a fresh git repository
- **THEN** `.troupe/actors/lead.yaml` names the runner `claude-code`, and `.troupe/actors/lead.md` holds its
  character
- **AND** standard output names `lead`, `claude-code` and both files

#### Scenario: Config shows the actor
- **WHEN** a person runs `troupe init --audition` and then `troupe config get actors.lead.runner`
- **THEN** it prints `claude-code`

#### Scenario: The character is changed through config
- **WHEN** a person runs `troupe init --audition`, then the `troupe config set actors.lead.character=@<file>` it names
  with a file of their own, then `troupe perform lead --rehearse`
- **THEN** `troupe config get actors.lead.character` prints the file's text, and the rehearsal isn't refused with
  `config.file-not-troupes`

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
