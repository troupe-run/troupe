# user-docs Specification

## Purpose

Capability: `cap:user-docs`

troupe's user documentation, which troupe.run's `/docs` is built from: where it lives, the page contract the site
builds from, which reference is generated and how it's kept true, how pages describe built and unbuilt behaviour,
and the vocabulary rules they follow.

## Requirements

### Requirement: The user docs live in docs/, laid out as the site's sections
troupe's user documentation SHALL live under `docs/`, as Markdown pages in the site's `/docs` sections: `programme/`,
`opening-night/`, `the-company/`, `stagecraft/`, `prompt-book/` and `backstage/`. A page's path under `docs/` SHALL be
its path under troupe.run's `/docs`. Documentation for people working on troupe itself SHALL live under
`contributing/`, never under `docs/`.

#### Scenario: A page and its published path
- **WHEN** the site builds `docs/the-company/theatres.md`
- **THEN** it publishes it at `/docs/the-company/theatres/`

#### Scenario: A contributor doc
- **WHEN** someone documents how the event store lays out its files
- **THEN** the page goes under `contributing/`, and nothing under `docs/` links to it by a relative path

#### Scenario: The pages the site has today
- **WHEN** the user docs are listed
- **THEN** they hold every page the website's `/docs` holds today, except `programme/status-and-roadmap.md` and
  `backstage/contributing.md`, which stay with the website

### Requirement: Every page carries the site's front matter
Every page under `docs/` SHALL start with front matter holding a `title` and a `description`, both non-empty strings,
and a `status` of `written` or `planned`. A `planned` page SHALL have a non-empty `purpose` and no body. A `written`
page SHALL have a body and SHALL set `prerelease` to `true` or `false` explicitly, never relying on the site's
default. Any other key, or a value of the wrong type, SHALL fail the docs check, naming the page, the key and what is
allowed.

#### Scenario: A page with a missing description
- **WHEN** a page's front matter has a `title` and no `description`
- **THEN** the docs check fails, naming the page and `description`

#### Scenario: An unknown key
- **WHEN** a page's front matter has `staus: written`
- **THEN** the docs check fails, naming the page, `staus` and the keys that are allowed

#### Scenario: A planned page with text
- **WHEN** a page with `status: planned` has a body
- **THEN** the docs check fails, naming the page, and says to set `status: written` or remove the body

#### Scenario: A written page that leaves prerelease out
- **WHEN** a page with `status: written` has no `prerelease` key
- **THEN** the docs check fails, naming the page, and says to set `prerelease: true` if the page describes behaviour
  troupe doesn't have yet, and `false` otherwise

### Requirement: A page's prerelease flag says whether it describes unbuilt behaviour
A page that describes any behaviour troupe doesn't have yet SHALL set `prerelease: true`. A page that describes only
what troupe does today SHALL set `prerelease: false`. The glossary defines words rather than behaviour, and SHALL set
`prerelease: false`.

#### Scenario: The glossary
- **WHEN** the glossary defines gate and cue before gates are built
- **THEN** it still sets `prerelease: false`

### Requirement: Pages about unbuilt behaviour invent nothing
A page SHALL describe unbuilt behaviour only as far as a decided issue or an accepted spec settles it. Where
something it covers is still undecided, the page SHALL say so and link the open issue that will decide it, opening
one when none exists, and SHALL NOT describe a design for it.

#### Scenario: A page about the house
- **WHEN** a reader opens the house's page before the house is built
- **THEN** the page says that the house isn't built yet
- **AND** the page describes what #73 and #14 decided about the house, and links the open issue for what they leave
  open

#### Scenario: A page about runs
- **WHEN** a reader opens the performances and runs page
- **THEN** what it says about `troupe perform`, `status` and `logs` is what the CLI does today
- **AND** it says that `troupe perform` runs one actor today, not a performance of the whole process

#### Scenario: A page about something nobody has decided
- **WHEN** a reader opens the flows page while no issue decides how flows work
- **THEN** the page gives only the decided definition, says the rest isn't decided yet, and links the issue that
  will decide it

### Requirement: Generated reference is regenerated, never hand-edited
A page with a generated region SHALL mark the region's start and end, and name its source. The docs check SHALL fail
when a generated region differs from what its source produces now, naming the page, the region and the command that
regenerates it.

#### Scenario: A new CLI option
- **WHEN** a change adds an option to `troupe status` and doesn't regenerate the CLI page
- **THEN** the docs check fails, naming `docs/prompt-book/cli.md`, the CLI region, and the command to run

#### Scenario: An edit inside a generated region
- **WHEN** someone edits a field's description inside the events region by hand
- **THEN** the docs check fails until the region is regenerated, and the fix says to change the schema instead

#### Scenario: No config schema yet
- **WHEN** `protocol/schemas/` has no config schema
- **THEN** the config schema page's generated region says there is no config schema yet, and the check passes
- **AND** once a config schema is added, the check fails until the region is regenerated from it

### Requirement: The reference pages generate what has a source
The user docs SHALL generate these regions: the CLI's commands, arguments, options and help text from the CLI's own
definitions; the exit codes from the exit-code enum; every event troupe records, with its fields and their
descriptions, from `protocol/schemas/events/`; and the config schema from `protocol/schemas/`.

#### Scenario: The events page
- **WHEN** a reader opens the events page
- **THEN** it lists every event schema under `protocol/schemas/events/`, each with every field its schema defines

### Requirement: The CLI page's examples run as written
Each console example in the CLI reference that starts `$ troupe` SHALL be run, and its documented output SHALL match
what troupe prints.

#### Scenario: A changed error message
- **WHEN** a change rewords the unknown-command error and the CLI page still shows the old text
- **THEN** the docs check fails, naming the example

### Requirement: The changelog page shows the release-please changelogs
The changelog page SHALL show every part that `release-please-config.json` writes a changelog for, by linking its
changelog or naming the part, and SHALL NOT copy their entries. The docs check SHALL fail when the page links a
changelog that `release-please-config.json` doesn't write, or shows a part neither way.

#### Scenario: A release PR
- **WHEN** a release pull request updates `packages/troupe/CHANGELOG.md`
- **THEN** the changelog page needs no edit, and the docs check passes

#### Scenario: A misnamed changelog
- **WHEN** the changelog page names `packages/troupe/CHANGES.md`
- **THEN** the docs check fails, naming the page, the path and the changelogs release-please writes

#### Scenario: A part left off the page
- **WHEN** `release-please-config.json` writes a changelog for `troupe-runner-ollama`, and the changelog page neither
  links that changelog nor names the part
- **THEN** the docs check fails, naming the page and the part, and saying to link its changelog or, before its first
  release, name it

### Requirement: The changelog page links only changelogs that exist
The changelog page SHALL link a part's changelog only once the file exists in the repository. Until a part's first
release, the page SHALL name it, without a link, as a list item that starts with its component name in code. The
docs check SHALL fail when the page links a changelog that doesn't exist. It SHALL pass when the page names a part
whose changelog exists, so a first release pull request isn't blocked.

#### Scenario: A link to a changelog not written yet
- **WHEN** `plugins/runner-ollama/CHANGELOG.md` doesn't exist, and the changelog page links it
- **THEN** the docs check fails, naming the page and the path, and saying to name `troupe-runner-ollama` without a
  link until its first release

#### Scenario: A part not released yet
- **WHEN** `plugins/runner-ollama/CHANGELOG.md` doesn't exist, and the changelog page has the list item
  `` - `troupe-runner-ollama` ``
- **THEN** the docs check passes

#### Scenario: A first release
- **WHEN** a release pull request writes `plugins/runner-ollama/CHANGELOG.md` for the part's first release, and the
  changelog page still names `troupe-runner-ollama` without a link
- **THEN** the docs check passes, and the page links the changelog in a later pull request, once the release has
  merged

### Requirement: Links between pages resolve
Every relative link in a page under `docs/` SHALL resolve to a page under `docs/`, and every `#anchor` it names SHALL
be a heading in that page. A link from `docs/` to the rest of the repository SHALL be an absolute GitHub URL, since
the site publishes only `docs/`.

#### Scenario: A link to a moved page
- **WHEN** a page links `../the-company/theater.md`, which doesn't exist
- **THEN** the docs check fails, naming the page, the link and the line

#### Scenario: A link to a missing heading
- **WHEN** a page links `cli.md#global-options` and the CLI page has no such heading
- **THEN** the docs check fails, naming the page, the link and the anchors the target has

#### Scenario: A relative link out of the user docs
- **WHEN** a page under `docs/` links `../../protocol/README.md`
- **THEN** the docs check fails, and says to use the file's GitHub URL

### Requirement: The glossary is the single source of troupe's vocabulary
`docs/prompt-book/glossary.md` SHALL hold one table row per term, each term in plain text. It SHALL have rows for
stage, rehearsal, audition, system and cue, and cue's meaning SHALL mark it as provisional. The glossary and the
house's page SHALL NOT call the house's name unconfirmed ("TBC", "isn't final").

#### Scenario: A term in code font
- **WHEN** a glossary row's term is written `` `system` ``
- **THEN** the docs check fails, naming the row, and says to write the term plainly and name any literal in its
  meaning

#### Scenario: A missing term
- **WHEN** the glossary has no row for rehearsal
- **THEN** the docs check fails, naming rehearsal

#### Scenario: No audition row
- **WHEN** the glossary has no row for audition
- **THEN** the docs check fails, naming audition

#### Scenario: A duplicate term
- **WHEN** the glossary has two rows for audition, at different places in the table
- **THEN** the docs check fails once, naming audition and that it has 2 rows, and says to keep one

#### Scenario: A duplicate that differs only in case or spacing
- **WHEN** the glossary has a row for "the house" and another for "The  House"
- **THEN** the docs check fails, naming the term as the first row writes it, and that it has 2 rows

### Requirement: The user docs say theatre for a theatre
Every line in `docs/` that says "project", "repo" or "repository" (or their plurals) SHALL be recorded, with the
reason it isn't a theatre: for example, explaining what a theatre is, troupe itself, or a git repository as git
means it. Every other use SHALL fail the docs check. A recorded use that's no longer in the docs SHALL fail it too.

#### Scenario: A new "project"
- **WHEN** a page says "run troupe in your project"
- **THEN** the docs check fails, naming the page and line, and says to say "theatre" or record the use with its reason

#### Scenario: "repo" for a theatre
- **WHEN** a page says "set up troupe in an existing repo"
- **THEN** the docs check fails, naming the page and line, and says to say "theatre" or "project directory"

#### Scenario: A recorded use that was edited away
- **WHEN** the line a recorded use matches no longer says "project"
- **THEN** the docs check fails, naming the recorded use as stale

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
