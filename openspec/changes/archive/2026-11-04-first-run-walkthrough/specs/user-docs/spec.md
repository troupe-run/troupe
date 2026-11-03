## ADDED Requirements

### Requirement: The first run leads with Claude Code and your own direction
The first-run walkthrough SHALL start from `troupe init --audition` in the reader's own repository, have them set the
`lead` actor's character from a file of their own with `troupe config set`, and run `troupe perform lead` with a
`--direction` they type. Each command it gives SHALL run as written in the docs check, with a stand-in `claude`.

#### Scenario: The Claude Code walkthrough runs as written
- **WHEN** the docs check runs each command the walkthrough gives, in order, in a git repository with a commit, with a
  stand-in `claude` on the path
- **THEN** `troupe init --audition` exits 0, and the `troupe perform lead --direction "..."` it gives prints
  `run <id> succeeded` and exits 0
- **AND** the `troupe diff`, `troupe accept`, `troupe status` and `troupe logs` it gives each exit 0 for that run

#### Scenario: The walkthrough's steps are the ones init prints
- **WHEN** the docs check compares the walkthrough's commit and allow commands with what `troupe init --audition`
  prints
- **THEN** they are the same commands

### Requirement: The first run has an offline path with the scripted runner
The first-run walkthrough SHALL give a way to try troupe with no account and no network: `troupe init --audition
--runner scripted` in a new repository, then the same steps. Each command it gives SHALL run as written in the docs
check, with no `claude` on the path.

#### Scenario: The offline walkthrough runs as written
- **WHEN** the docs check runs each command of the offline path, in order, in a new git repository with no `claude`
  on the path
- **THEN** its `troupe perform lead` prints `run <id> succeeded` and exits 0

### Requirement: The first run explains the notice for uncommitted changes
The first-run walkthrough SHALL say that a run works from the latest commit, and show the `workspace.uncommitted-unseen`
notice `troupe perform` sends when the theatre has changes the run won't see, with its fix. The page's copy of the
notice SHALL be the text `troupe perform` sends.

#### Scenario: The page's notice is the one perform sends
- **WHEN** the docs check runs the walkthrough's `troupe perform` with a file changed since the last commit
- **THEN** standard error holds the notice as the page shows it, with the page's example count and commit read as the
  run's own

### Requirement: The first run gives the local-stage permission once
The first-run walkthrough SHALL say to add the line that allows the local stage to the reader's shell profile once,
naming `~/.zshrc`, `~/.bashrc` and the PowerShell profile, and that it then applies to every theatre they run. It
SHALL give the line for sh and for PowerShell, and SHALL NOT add a place troupe reads policy from.

#### Scenario: The allow line is the one policy reads
- **WHEN** the docs check runs the walkthrough's `troupe perform` without the allow line's variable, then with the
  value the page's line sets
- **THEN** the first is refused naming `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true`, and the second succeeds

#### Scenario: The page names the shell profiles
- **WHEN** the docs check reads the walkthrough's section on allowing the local stage
- **THEN** it names `~/.zshrc`, `~/.bashrc` and the PowerShell profile, and both the `export` and the `$env:` forms
