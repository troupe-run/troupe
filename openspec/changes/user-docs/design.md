# Design

## Context

- **The website today** has 31 pages under `src/content/docs/docs/`, in six sections.
  - Six are written: `what-is-troupe`, `principles`, `licensing`, `glossary`, `status-and-roadmap` and
    `contributing`. The last two stay with the website (website#23).
  - The other 25 are `status: planned`, holding only a `purpose`.
  - The site's front-matter schema (`src/content.config.ts`) extends Starlight's with three keys:
    - `status`: `written` or `planned`, defaulting to `planned`;
    - `prerelease`: a boolean, defaulting to `true`;
    - `purpose`: a string.
  - A `planned` page renders "Planned: not written yet" with its purpose. A `written` page with `prerelease` renders
    "Pre-alpha: this page describes intended behaviour".
- **The website's `tests/unit/vocabulary.test.ts`** holds the docs to the vocabulary rules. It requires "theatre",
  never a bare "project", with each other use recorded. It checks that the glossary has stage, rehearsal, system and
  cue, that cue is provisional, and that the house's name isn't TBC. Once the docs leave the website, none of this
  sees them, so it has to move with them.
- **troupe's `docs/`** holds contributor docs:
  - `runs.md`, `runners.md`, `event-store.md`, `platform.md`, `releasing.md` and `flake-hunt.md`, which cite
    issues and designs;
  - `cli/README.md` and `cli/exit-codes.md`, which are user reference.
  - Six tests tagged `docs` hold them to the code, for example by running `cli/README.md`'s console examples and
    comparing `exit-codes.md`'s table with `ExitCode`.
- **What troupe does today:** `perform`, `status` and `logs`, runs recorded with lineage in a text event store, the
  runner contract with a scripted runner, the local stage behind a policy setting, and the identity chain.
  - There's no config (#60), no config schema in `protocol/schemas/`, no house, no flows, guests or gates, and no
    release yet. Release PR #89 is open.
- **release-please writes one `CHANGELOG.md` per package, nine in all.** Their versions are linked, and the release
  PR edits them. A release PR touches package paths, so it runs the full check, docs tests included.

## Goals / Non-Goals

**Goals:**
- Every page the site's `/docs` will show (except the two the website keeps) has its source here, valid against the
  site's schema, so website#23 can build from it without fixing anything up.
- Each checkable claim in a page is held to its source: generated regions to the code and schemas, examples to what
  the CLI prints, links to their targets, words to the glossary.
- Pages about unbuilt behaviour are traceable, claim by claim, to a decision (the table in D6).

**Non-Goals:**
- Rendering, versions, the version menu, edit links and the rebuild notice (website#23).
- A Node toolchain in troupe's CI.
- Writing a page's content for behaviour nobody has decided.

## Decisions

### D1. `docs/` is the user docs; the contributor docs move to `contributing/`

Every published page sits under `docs/` at its site path (for example `docs/the-company/theatres.md`), so the loader
in website#23 maps the tree one to one. The contributor docs move with `git mv`, so their history follows:
`contributing/runs.md`, `runners.md`, `event-store.md`, `platform.md`, `releasing.md` and `flake-hunt.md`.

`docs/cli/README.md` and `docs/cli/exit-codes.md` are user reference, so they become `docs/prompt-book/cli.md`:
- the prose sections (conventions, values that start with `-`, errors and their console examples) are kept as
  written;
- the command and option tables and the exit-code table are replaced by generated regions (D3).

`test_cli_docs` and `test_exit_codes_doc` move their target to the new page.

- *Alternative: user docs in `docs/user/`.* The owner chose to move the contributor docs instead (2026-10-19). It
  gives the published tree the shorter, clearer root, and leaves no published and unpublished docs side by side
  under one folder.
- *Alternative: a top-level `user-docs/`.* It needs a scope of its own, and leaves `docs/` meaning "not the docs".

Every reference to a moved path follows it, found by `git grep` for `docs/` outside `openspec/changes/archive/`.
That covers the READMEs, `protocol/`, comments in `troupe.core` and `troupe.platform`, the scripts, the release
workflow's comment, the fixtures' `provenance.json` and the tests. Archived changes keep the paths they were written
with: they're history.

### D2. The front matter is the site's schema, closed

The docs check reads each page's front matter as a strict subset of YAML (`packages/troupe/tests/userdocs.py`):
- one `key: value` per line;
- each value is a double-quoted string (with JSON's escapes), a single-quoted string, `true`, `false`, or a plain
  scalar that YAML reads as the same string;
- a key set twice, or a value YAML would read as something else (`yes`, `12`, `a: b`, `[a]`), is refused with how to
  quote it.

troupe has no YAML library, and a subset that refuses everything else means the same to the site's loader without
adding one. It allows exactly
`title`, `description`, `status`, `prerelease` and `purpose`, with the types and rules in the spec. That's stricter
than the site in three ways:
- Unknown keys fail, where Zod would strip them silently.
- A written page must state `prerelease`, where the site would default it to `true`.
- A planned page must have no body.

Each of these turns a silent mistake into a named failure (the constraint that malformed input is an error). The
allowed keys live in one constant beside the test, which says that website#23's schema must match it. When the site
gains a key, both change in step.

- *Alternative: validate with the site's Zod schema in Node.* That's the render check, deferred (D8).

### D3. Generated regions, regenerated by one script, checked by a test

A generated region is delimited by HTML comments, which Markdown doesn't render:

```markdown
<!-- generated: cli (from troupe.cli.COMMANDS; regenerate with `uv run scripts/docs_reference.py`) -->
...
<!-- end generated: cli -->
```

`scripts/docs_reference.py` builds every region from its source and rewrites only what's between the markers, so the
prose around a region is never touched. With `--check`, it changes nothing and reports each stale region. The test
`packages/troupe/tests/test_user_docs_reference.py` (tagged `docs`) loads the script by path. It fails naming the
page, the region and the regenerate command, and its fix says to edit the source, not the region.

| Region | Page | Source | Renders |
|---|---|---|---|
| `cli` | `prompt-book/cli.md` | `troupe.cli.COMMANDS` and the global options, through the parsers they configure | Each command's usage line, its summary, and a table of its arguments and options with their help, required and repeatable marks, and mutually exclusive groups. The global flags |
| `exit-codes` | `prompt-book/cli.md` | `troupe.core.exit_codes.ExitCode` and its members' docstrings | Code, name and meaning |
| `events` | `prompt-book/events.md` | `protocol/schemas/events/*.schema.json` and `lineage.schema.json` | One section per event (title, description, topic), and a table of its fields: name, type, required, description. Lineage once, linked from each event |
| `config` | `prompt-book/config-schema.md` | `protocol/schemas/config/` | The config schema's fields, rendered as for events. While the directory doesn't exist, one line: there is no config schema yet, with a link to #60 |

The script lives in `scripts/` but isn't in the `scripts` scope, because a new file there is in no scope until it's
declared. So a change to it runs the full check, which is right for a file that reads core and `protocol/`. The test
lives in the core suite, which already reaches every package, so the reach check doesn't change.

The exit codes' meanings come from the enum's member docstrings, which `exit_codes.py` already has. Python doesn't
keep a member's docstring at runtime, so the generator reads them from the module's source with `ast`, and fails
naming the member when one has none. The enum stays the single place the codes are defined, and the hand-written
table's wording gives way to the docstrings'. The docstrings are reviewed as user-facing prose: CANCELLED's says
"A person cancelled", the table says "You cancelled".

The CLI's help strings become user-facing reference, so the implementation reviews them as prose. A help string that
reads badly in the reference is fixed in the code, and the region regenerated.

- *Alternative: generate at site build time.* That moves the generator into website#23 and Node, and the PR that
  changes the CLI couldn't show its docs change in its diff.
- *Alternative: whole generated pages.* The CLI page's conventions and examples are prose, and so is the events
  page's introduction. Regions keep them in one page.

### D4. The changelog page links the changelogs; it doesn't copy them

`docs/backstage/changelog.md` is written:
- it explains that each package has its own changelog, written by release-please from the Conventional Commits, with
  linked versions;
- it lists each changelog by its GitHub URL.

The test reads `release-please-config.json` and fails when the page's set of changelog paths differs from the
packages it declares (each package's `CHANGELOG.md`, as the releases spec says).

A copied changelog would go stale on every release PR, and a release PR runs the full check. It would then fail, or
need release-please to regenerate a docs page, which it can't. Links can't go stale. Embedding the changelogs in the
rendered page is website#23's to choose, since it builds each version from its tag.

### D5. The vocabulary rules move here, extended to "repo"

`packages/troupe/tests/test_user_docs_vocabulary.py` (tagged `docs`) ports the website test's docs rules:
- every line in `docs/` that says "project", "repo" or "repository" is recorded in a list in the test module, with a
  line fragment and a reason, and an unrecorded use fails;
- a recorded use that no longer matches any line fails as stale;
- the glossary has rows for stage, rehearsal, system and cue, and cue is provisional;
- neither the glossary nor the house's page says "TBC" or "isn't final";
- glossary terms are plain text: a backtick in a term cell fails.

Only `docs/` is scanned. `contributing/` isn't published, and talks about the repository as a repository.

The website's brand-guide checks (§6 matching the glossary) stay with the website. They need the brand guide, so
website#23 points their `GLOSSARY` at troupe's file.

The glossary's `system` row becomes "system | troupe acting by itself, recorded as an actor of kind `system`. It's how
lineage shows a change troupe observed, such as a merge" (owner, #123, 2026-10-19).

### D6. Which pages describe the code and which describe intent

A sweep of every Decision and placeholder issue, the accepted specs and `docs/` sorted the 25 pages into three kinds:
- **code**: the page describes what troupe does today, with `prerelease: false`;
- **intent**: decided but unbuilt, with `prerelease: true`;
- **undecided**: only a definition or a principle exists. The page states that much, says the rest isn't decided
  yet, and links the issue that will decide it, with `prerelease: true`.

A page mixing kinds is `prerelease: true`, and its built parts are held to the code like any other.

| Page | Kind | Built today, and decided | Waits on |
|---|---|---|---|
| `opening-night/install` | undecided | No release yet. Releases are GitHub releases with changelogs (releases spec). Python 3.12 to 3.15 on all three OSes. The CLI and the house ship as one unit (#73), and the per-user home is `~/.troupe/` or `TROUPE_HOME` (#2) | #38 (question 4: how troupe ships) |
| `opening-night/first-theatre` | code + intent | A theatre is found upwards by `.troupe/` and never created for you. Today `.troupe/` is made by hand, and its layout is known. Config files by convention (#6), `$schema` (#7), `troupe config set` (#60). Says "project directory", not "repo" | A setup command: none is decided, recorded as open on #60 |
| `opening-night/first-performance` | code + intent | `perform` one actor with the scripted runner, then `status` and `logs --follow`, with the policy setting. That's one actor's run, said plainly: a performance of the whole process isn't built | #55, #60, #62 |
| `prompt-book/cli` | code (generated) | D3 | |
| `prompt-book/events` | code (generated) | D3 | |
| `prompt-book/config-schema` | intent (generated region empty) | The rules: JSON Schema is the source, one schema per file kind, strict, `$schema` in every file (#6, #7) | #60 |
| `prompt-book/guest-manifest` | undecided | Guests bring their own file kinds and schemas, registered by path pattern (#6, #7). Acquired plugins run over JSON-RPC (#37), named and pinned in config (#38) | A new issue for guests |
| `stagecraft/bring-your-own-agent` | code + intent | The runner contract, publishing a runner's schemas, the conformance suite. Claude Code next (#55), then a local model (#56). Plugins over JSON-RPC (#37), the SDK (#58) | #38 and #67 (naming a runner in config), #55 |
| `stagecraft/build-a-flow` | undecided | The principle "tasks fork, join, swarm and loop". A flow can stop at a gate (#62) | A new issue for flows |
| `stagecraft/configure-roles` | intent | Work flows to roles, not to people or agents. Holders and the role are recorded in lineage (#15, #61). Agents' identity comes from the actor (#9). The identity chain today | #44, #61 |
| `stagecraft/hand-edit-config` | intent | Net change at command boundaries, formatting and comments kept (#5, #119). Until #119, a hand-edited file is refused with a fix (#60) | #119, #45 |
| `stagecraft/read-the-lineage` | code + intent | `status`, `logs` and `--json` for runs, and each lineage field. Who approved what comes with gates | #62, #61 |
| `stagecraft/route-decisions` | intent | Gates, escalations and cues are addressed to a role, and whoever holds it picks them up (#15, #62) | #61, #44, #12 |
| `stagecraft/write-a-guest` | undecided | As guest-manifest. Writing a runner plugin is the nearest built thing, linked | A new issue for guests |
| `the-company/escalation` | undecided | Addressed to a role, research first, then a brief (#15, #62, the glossary) | A new issue for escalation and the decision brief |
| `the-company/flows` | undecided | The principle only | A new issue for flows |
| `the-company/gates-and-decisions` | intent | Gates are addressed to a role, raise a cue, and record the answer with lineage. `approvals` is empty until gates exist (#15, #62, #73) | #62, #12 |
| `the-company/guests` | undecided | The definition, and the name agreed "for now" (#15). Title "Guests": "pack" is a rejected name | A new issue for guests |
| `the-company/lineage` | code + intent | Every field and rule, the identity chain, transcripts by hash (#4). Role and approvals to come | #44, #62 |
| `the-company/notes` | undecided | The term (#15) and the glossary line | A new issue for notes |
| `the-company/performances-and-runs` | code + intent | Runs: events, states, outcomes, Ctrl-C (runs spec). Rehearsal (#15), the house supervising runs (#73), a worktree per run (#51). Says that `perform` runs one actor today | #63, #51 |
| `the-company/roles-and-actors` | code + intent | Actors and their lineage kinds today. Roles, and the `system` kind (decided, not yet in the lineage schema) (#15) | #61, #44 |
| `the-company/the-house` | intent | The only orchestrator, per user, auto-started with a notice, CLI and house as one unit, events stay the truth (#73). `~/.troupe/house.yml` (#2), the sweep (#5), the gateway (#14), turning auto-start off (#118). Command names "or similar" are given as provisional | #63 |
| `the-company/theatres` | code + intent | Found by `.troupe/`, its layout today, git or plain files. Config by convention, project config only in the theatre (#2, #6, #7) | #60, #8, #121 |
| `backstage/changelog` | code | D4 | |

Four subjects have no issue at all: flows, notes, escalation's research steps and decision brief, and guests and
their manifest. The spec requires an undecided page to link the issue that will decide it, so the apply opens one
placeholder Feature issue for each of the four in troupe-run/troupe and adds it to the roadmap board. Each issue says
only what's decided and what's still to decide, and cites the page.

The moved written pages keep their text, with these changes:
- `what-is-troupe` and `principles` describe intent, and become explicitly `prerelease: true`, which the site
  already defaults them to.
- `licensing` stays `false`.
- The glossary defines words, not behaviour, so it stays `prerelease: false`, as the website has it, even where a
  word's behaviour is unbuilt. The spec says so.

Each page's prose is checked against this table during the apply. A sentence about unbuilt behaviour that the table's
sources don't support is cut, or turned into "not decided yet".

### D7. Links resolve inside `docs/`, with anchors the way the site makes them

`packages/troupe/tests/test_user_docs_links.py` (tagged `docs`) reads every Markdown link and reference in `docs/`
outside code blocks and generated regions:
- A relative link must name a page under `docs/`, by its `.md` path.
- Its `#anchor` must be a heading slug in the target, made as the site makes them (github-slugger: lowercase, drop
  punctuation, spaces to hyphens, with `-1`, `-2` for repeats).
- An absolute URL isn't fetched. Only its form is checked: `https://github.com/troupe-run/...` for files in this
  repository.

How the site turns `.md` links into page URLs is website#23's concern. This check holds the source tree to links
that can be mapped.

### D8. No render check yet

The owner chose Python checks now and the render check later (2026-10-19). Today the website can't load docs from
troupe, so a render check would mean copying files into its tree, the very coupling website#23 replaces. The
front-matter, link and vocabulary checks catch most of what a render would, on all three OSes.

### D9. The rebuild notice stays with website#23

#120's closing comment lists "the notice to the website" under #123. website#23 says it owns both ends, the website's
side and "the sending step in troupe-run/troupe's workflows (a small PR there)", using infrastructure#109's
credential. That's more specific, and it pairs the notice with the receiver it has to match. This change doesn't add
it. The PR description names the conflict so the owner can confirm.

## Risks / Trade-offs

- **[Intent pages go stale as features land]** → Each feature's change rewrites its page, as the CLAUDE.md rule
  "specs, code and tests in agreement" already asks of docs. The `prerelease: true` flag shows the reader. D6's
  table names the issue each page waits on, so the change that closes it knows which page to update.
- **[Moving `docs/` breaks outside links to the contributor docs]** → None are known outside this repository. GitHub
  doesn't redirect moved files. The PR description lists the moves.
- **[The site's schema and D2's constant drift]** → The constant's comment names website#23. Until the render check
  exists, the two are kept in step by hand: one constant here, one schema there.
- **[Help strings written for `--help` read poorly as reference]** → They're reviewed in the implementation (D3), and
  the CLI's own tests still hold `--help`'s output.
- **[A slugger mismatch makes an anchor check pass that the site would break]** → The test covers the cases the docs
  use (punctuation, code spans, repeats) against slugs from github-slugger's own test cases.

## Migration Plan

1. Move the contributor docs and update every reference. Run the full check.
2. Add the user docs: the moved written pages, the glossary, and the 25 pages.
3. Add the generator, the generated regions and the checks. Run the full check.

Rollback is reverting the PR. Nothing outside this repository reads `docs/` until website#23 lands. The website's
`/docs` stays frozen until then (#123).
