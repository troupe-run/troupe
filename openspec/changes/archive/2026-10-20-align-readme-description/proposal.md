# Proposal

Issue: #130 (sub-issue of troupe-run/infrastructure#108).

## Why

The owner agreed on 2026-10-20 how troupe is described everywhere it's introduced (troupe-run/infrastructure#108).
GitHub's side is live: the org's description, this repository's description and topics, and the org profile all carry
the agreed sentence, from `tofu/descriptions.json` in troupe-run/infrastructure. The README still opens with the old
sentence ("…with agents and people in named roles") and the old status line, so it no longer matches the org profile
a reader sees one click away.

Six other places in this repository introduce troupe with the same old one-liner. They aren't listed in #130 or
troupe-run/infrastructure#108, but the owner chose on 2026-10-20 to bring them into step in this change too, rather
than leave them to drift.

## What Changes

- **The paragraph under the tagline** becomes: "troupe runs your development process with a team of agents, asking
  only when it needs you. Work branches and loops, decisions go to whoever owns them, and every decision records who
  made it." This is the declared sentence followed by the README's existing second sentence, word for word as in the
  org profile.
- **The tagline**, "**Your agents need a director.**", stays as it is.
- **The status paragraph** opens with the declared status line, "Pre-alpha: there's nothing to install yet.", in
  place of "**Status: pre-alpha.** There's nothing to install yet.". The rest of the paragraph, what exists so far and
  the links to troupe.run and the roadmap, stays as it is.
- Nothing else in the README changes.
- **The other six places** drop "…with agents and people in named roles" for the agreed sentence, or a variant of it
  that fits where it appears (the design lists each one's exact text):
  - `docs/programme/what-is-troupe.md`, published on troupe.run: its front-matter `description` and its opening line.
  - `packages/troupe/pyproject.toml`: the package `description`.
  - `packages/troupe/src/troupe/__init__.py`: the package docstring.
  - `packages/troupe/src/troupe/cli/parser.py`: the description `troupe --help` prints.
  - `CLAUDE.md`: its opening sentence.
  - `openspec/config.yaml`: the opening sentence of the project context.

### Out of scope

- The website's hero, page title, meta description and brand guide: troupe-run/website#26.
- Single-sourcing the text so these places can't drift from the declaration: troupe-run/troupe#120.
- Rewording anything beyond the one-liner in those places. The rest of each one stays as it is.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None: wording only. The `--help` description isn't in any spec or test, and no requirement changes. The change
declares `skip_specs`.

## Impact

- `README.md`: two paragraphs at the top. `docs/programme/what-is-troupe.md`, `CLAUDE.md`, `openspec/config.yaml`:
  one sentence each. `packages/troupe`: the package description, the docstring and the `--help` description.
- Visible effects: the README on GitHub, the "What is troupe?" page on troupe.run after the next release (the release
  tells troupe.run that `docs/` may have changed), `troupe --help`, and the package's summary when it's next built.
- The root `README.md` and `CLAUDE.md` are in no check scope, so the commits run the full check, as do the pull
  request's CI legs.
- The PR closes #130. troupe-run/infrastructure#108 stays open until the website's sub-issue (troupe-run/website#26)
  is done too.
