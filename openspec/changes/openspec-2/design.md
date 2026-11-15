# Design

## Context

See proposal.md, Why. troupe's generated OpenSpec files come from the CLI's Claude Code integration with the six
default workflows: six skills in `.claude/skills/openspec-*/` and six commands in `.claude/commands/opsx/`, all
`generatedBy: "1.14.3"` (archived change `openspec-1-14-2`). OpenSpec 2.0.0 is installed locally from Homebrew
(`openspec --version` prints `2.0.0`).

2.0 keeps one copy of each skill in `.agents/skills/` and links tool folders to it, retires the `delivery` setting
and the `/opsx:*` commands, and has `openspec update` remove what older versions generated
([release notes](https://github.com/Fission-AI/OpenSpec/releases/tag/v2.0.0),
[upgrade guide](https://openspec.dev/docs/upgrade-to-2)). The guide maps each command to a skill of the same
workflow: `/opsx:propose` → `openspec-propose`, `/opsx:explore` → `openspec-explore`, `/opsx:apply` →
`openspec-apply-change`, `/opsx:update` → `openspec-update-change`, `/opsx:sync` → `openspec-sync-specs`,
`/opsx:archive` → `openspec-archive-change`. In Claude Code a skill is typed as `/<name>`.

Who reads the old names in this repository: `CLAUDE.md` (workflow steps 2, 3 and 6), the generated files themselves,
and the archived changes. `scripts/guard.py` and `.github/workflows/guard.yml` name them too, but they're delivered
(`.github/guard-delivery.json`), and the guard refuses an edit to a delivered file outside delivery.

## Goals / Non-Goals

**Goals:**
- The generated files are exactly what `openspec update` 2.0.0 writes, with no hand edits.
- No live text in this repository tells a person or agent to type a `/opsx:*` command.

**Non-Goals:**
- Changing the delivered guard (`guard.py`'s messages, `guard.yml`'s `OPENSPEC_VERSION`). That's
  troupe-run/infrastructure#308, delivered once this and website#116 have merged.
- Rewriting archived changes. They record what was typed when they were written.
- Adding the optional workflows (new, continue, ff, verify, bulk-archive, onboard), or linking tools other than
  Claude Code. Those are profile changes, not a version bump.
- Skipping `.claude/**` or `.agents/**` in `scripts/check-paths.toml` (as in `openspec-1-14-2`: a separate decision).

## Decisions

**D1. Regenerate with the installed 2.0.0, checked by a dry run and a second run.** `openspec --version` must print
`2.0.0`. The dry run is the expected list; the real run must match it exactly, and running it again must change
nothing (the guide says a second run is a no-op). The alternative, `npx @fission-ai/openspec@2.0.0`, gives the same
version; the installed one is what every session here uses, so it's the one checked.

**D2. Commit the links as links.** The guide says to commit them like other files. On Linux and macOS they check out
as links. On Windows without `core.symlinks` they check out as small text files naming the target; the guide's
fix for a Windows contributor is `core.symlinks=true` and Developer Mode, after which `openspec update` repairs a
copy. CI's Windows job doesn't read `.claude/skills/` (no test, check or workflow does: checked with grep across
`scripts/`, `packages/`, `plugins/` and `.github/workflows/`), so the Windows leg is unaffected. No troupe
contributor runs Claude Code on Windows today; if one does, the upgrade guide's two settings are the fix.

**D3. CLAUDE.md names the skills by their 2.0 names, typed as slash commands.** `/openspec-propose <name>`,
`/openspec-apply-change`, `/openspec-archive-change`. These are the names the upgrade guide gives and the names
Claude Code lists. Writing "the propose skill" instead would leave the reader to find the name.

**D4. `skip_specs: true`.** No troupe requirement changes, and no spec names a command or the skill folders.

## Risks / Trade-offs

- [`openspec update` touches a file outside the dry run's 25, such as `openspec/config.yaml`] → task 1.2 compares
  `git status` with the list. Revert any extra file and report it.
- [Between this merge and infrastructure#308's delivery, the guard's messages still say `/opsx:propose`] →
  accepted. The skill it means exists under its 2.0 name, and CLAUDE.md gives that name. #308 follows directly.
- [CI validates with 1.14.3 while the repository is on 2.0's layout] → `openspec-strict` reads only `openspec/`,
  whose format 2.0 doesn't change; task 2.2 runs 1.14.3's strict validation over the result to show it.
- [Sessions mid-change on `/opsx:*`] → they keep the commands they loaded. A branch rebased onto this loses them;
  the same workflows are the `openspec-*` skills, which also existed under 1.14.3. The orchestrator tells running
  sessions the names before this merges.
