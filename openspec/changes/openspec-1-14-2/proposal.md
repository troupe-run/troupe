# Proposal

## Why

troupe's generated OpenSpec skills and commands say `generatedBy: "1.14.1"`. These files drive every change's
workflow, so they should come from a current OpenSpec. Issue #113 asked for 1.14.2, the version installed locally and
used by troupe-run/website (#6). 1.14.3 was published on npm on 2026-10-17, and on 2026-10-18 the owner chose it
instead. troupe then runs ahead of the website and of troupe-run/infrastructure until they move too.

Separately, `.claude/settings.local.json` is ignored only by the owner's personal git config, so anyone else could
commit theirs. The owner folded the `.gitignore` line into this change on 2026-10-16.

## What Changes

- **Regenerate the OpenSpec files with 1.14.3.** Run `npx -y @fission-ai/openspec@1.14.3 update`; don't hand-edit.
  It changes exactly 9 generated files:
  - From 1.14.2, `openspec-explore` and `/opsx:explore`: with a schema other than the default, insights go into
    whichever artifact the schema defines, and the example offers no longer name `design.md`.
  - From 1.14.2, `openspec-update-change` and `/opsx:update`: besides files that already exist, edits may go to a
    confirmed concrete path under a partly filled glob artifact.
  - From 1.14.3, `openspec-explore`, `openspec-propose`, `/opsx:explore` and `/opsx:propose`: before writing an
    artifact, the agent picks its output path. For a glob, the path must stay inside the change's root after
    symlinks are resolved. A skill the artifact delegates to is used only if it can write to that path. Otherwise
    the agent stops and tells the user.
  - The other three skills: only `generatedBy` moves to `1.14.3`.
- **Ignore `.claude/settings.local.json`** in the repository's own `.gitignore`, the same line the website uses.

Nothing else changes. `openspec/config.yaml` and `.claude/settings.json` stay as they are. `settings.json` is
outside `openspec update`'s scope and is delivered from troupe-run/infrastructure.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. These are development tooling files. No troupe behaviour, and no requirement in `openspec/specs/`, changes,
so the change sets `skip_specs: true`.

## Impact

- Changed: `.claude/skills/openspec-*/SKILL.md` (6), `.claude/commands/opsx/explore.md`,
  `.claude/commands/opsx/propose.md`, `.claude/commands/opsx/update.md`, `.gitignore`. That's 29 lines added and
  22 removed.
- Unchanged: `openspec/config.yaml`, `.claude/settings.json`, all code and tests.
- The commit runs the full check: `.claude/**` and `.gitignore` aren't in `scripts/check-paths.toml`.
- Follow-ups: troupe-run/infrastructure#58 and troupe-run/website move to 1.14.3 in their own pull requests. #113's
  title and body are updated to say 1.14.3.
- Rollback: revert the commit.
