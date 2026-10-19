# Proposal

## Why

troupe-run/troupe#120 decided that everything under troupe.run's `/docs` comes from this repository, so a user-facing
change and its docs land in one PR, checked by the tests that already hold `docs/cli/exit-codes.md` to the code.
troupe-run/troupe#123 builds that. Its precondition, the glossary's agreed changes (troupe-run/website#22), merged on
2026-10-19. Until troupe-run/website#23 switches the site over, the website's `/docs` is frozen, so its 25 empty
placeholder pages are written here instead (owner, #123, 2026-10-19).

## What Changes

- **`docs/` becomes the user docs.** It's laid out as the site's `/docs` sections: `programme/`, `opening-night/`,
  `the-company/`, `stagecraft/`, `prompt-book/` and `backstage/`. Each page carries the site's front matter (`title`,
  `description`, `status`, `prerelease`, `purpose`).
- **The contributor docs move to `contributing/`.** That covers `runs.md`, `runners.md`, `event-store.md`,
  `platform.md`, `releasing.md` and `flake-hunt.md`. Every link and comment that names them follows (owner,
  2026-10-19). `docs/cli/README.md` and `docs/cli/exit-codes.md` are user reference, so they fold into
  `docs/prompt-book/cli.md` instead.
- **Moved from the website as written:** `programme/what-is-troupe` and `principles`, `backstage/licensing`, and the
  glossary with #22's changes. The glossary's `system` row also gets the owner's 2026-10-19 fix: a plain term, with
  the literal named in the meaning.
- **All 25 placeholder pages are written** (owner, 2026-10-19).
  - The pages for what troupe does today describe the code, and tests check them against it where it can be
    checked.
  - The pages for what isn't built yet describe intended behaviour, drawn only from decided issues and accepted
    specs. They're marked `prerelease: true`, which the site renders as "describes intended behaviour".
  - Where nothing is decided, the page says it's undecided and names the open issue, instead of inventing a design.
  - "Your first theatre" says "project directory", not "repo".
- **Generated reference.** Generated regions are kept in the page and checked by a test that fails when they're
  stale, naming the command that regenerates them:
  - the CLI's commands, arguments and options from its definitions;
  - the exit codes from `ExitCode`;
  - the events and their fields from `protocol/schemas/events/`;
  - the config schema from `protocol/schemas/` once a config schema exists there. There's none yet (#60), so until
    then the region says so.
- **The changelog page.** It's written here and names the release-please changelogs it shows. It's never a
  hand-copied changelog, so a release PR can't make the docs stale.
- **Checks on every OS, in Python:**
  - front matter is valid against the site's schema;
  - every relative link and anchor resolves;
  - glossary terms are written in plain text;
  - the vocabulary rules the website enforced on its `/docs` now apply here: "theatre", never a bare "project",
    and the house's name is agreed.
- **No render check.** Building the website against a PR's docs waits for website#23 (owner, 2026-10-19).
- **The `docs` scope** covers `docs/**` and `contributing/**`, so a change to either runs the docs tests.

Out of scope:
- The site's loader, version menu and edit links (website#23).
- The step that tells the website to rebuild. #120's closing comment lists "the notice to the website" under #123,
  but website#23 says it owns both ends of that trigger, and it's the more specific of the two. This change leaves
  the notice to website#23 and records the conflict for the owner to confirm.
- The brand guide's §6 links and `system` row, which live on the website (website#23).
- Removing the pages from the website, which website#23 does.

## Capabilities

### New Capabilities
- `user-docs`: troupe's user documentation. Where it lives, the page contract the site builds from, which pages are
  generated and how they're kept true, how pages describe built and unbuilt behaviour, and the vocabulary rules.

### Modified Capabilities
- `quality-check`: the `docs` scope covers `docs/**` and `contributing/**` (and still the scripted runner's README),
  and the scenarios that list the tagged documentation tests name the new ones.

## Impact

- **Moved:** every file under `docs/`, plus every reference to those paths:
  - the root and package READMEs, `plugins/README.md`, `protocol/README.md` and one schema description;
  - comments in `troupe.core.defaults`, `errors`, `notices`, `exit_codes` and `troupe.platform.processes`;
  - `.github/workflows/release.yml`'s comment, the scripts that cite `docs/flake-hunt.md`, and the docs tests'
    paths.
- **New:** a generator script for the generated regions, and tests tagged `docs` for front matter, links,
  vocabulary and generated regions. `scripts/check-paths.toml` changes, which runs the full check once.
- **Website:** nothing changes there in this PR. website#23 reads `docs/` from troupe. The GitHub URLs to the moved
  contributor docs change, so outside links to `docs/runs.md` and the rest break. None are known outside this
  repository's own specs and archives.
- **Infrastructure:** `docs/development-workflow.md` quotes troupe's old declaration as an example, and it stays
  accurate as an example.
