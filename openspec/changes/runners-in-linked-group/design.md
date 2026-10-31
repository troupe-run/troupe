# Design

## Context

See proposal.md for why. Today `scripts/release_config.py`'s `_group_problems` expects the `troupe` linked group to
be exactly the `packages/*` workspace members: it names any missing one, and refuses anything else as "only
packages/* members belong there" (`test_a_plugin_in_the_linked_group_is_named` pins that). `scripts/bundle.py`
separately checks that `troupe-run` depends on every other workspace member, and it imports `members` from
`release_config`, so `release_config` can't import from `bundle` without a cycle.

Every component in `.release-please-manifest.json` is at 0.0.0 and origin has no tags, so the runners joining the
group moves no version: the first release is 0.1.0 for all of them either way. release-please's linked-versions plugin
releases every component in a group when any of them has a releasable commit, at the group's highest next version.

## Goals / Non-Goals

**Goals:**
- A runner-only releasable commit releases the bundle, through the group alone.
- The check's idea of the group follows what the bundle ships, so a future bundled package (#56, #162) can't be left
  out, and a runner taken out of the bundle (#38, #67) must leave the group too.

**Non-Goals:**
- Moving runners out of the bundle or the repository (#38, #67).
- How dependency updates release (troupe-run/infrastructure#240).
- Changing the protocol's own release, or the tags each component gets: every component keeps its own
  `<component>-v<version>` tag and changelog.

## Decisions

### D1. The group is `packages/*` plus the bundle's workspace dependencies

The expected group is the `packages/*` members together with every workspace member named in `troupe-run`'s
`[project] dependencies`. Today that's every workspace member, but it's derived from the bundle rather than from
`plugins/*`, because the bundle is what the rule is about: "the bundle ships the latest release of everything in it".

- *Alternative: every workspace member.* Same result today, but it would keep a runner in the group after it leaves
  the bundle and before it leaves the repository, when it should version on its own.
- *Alternative: only the bundle and its dependencies, dropping `packages/*`.* A `packages/*` member the bundle forgot
  would then fall out of the group silently, and only `bundle.py` would say so. Keeping both means each check stands
  on its own.

### D2. Read the bundle's dependencies from its `pyproject.toml`, found by name

`release_config` finds the bundle's directory from `members(root)` by its project name, `BUNDLE`, and reads that
member's `pyproject.toml`. It doesn't take the path from the release config (`bundle_path`), because a broken config
is what the check reports on, and it doesn't hold `packages/troupe-run` as a literal, which would widen every suite
that imports the module (`check_paths_reach.py`, rule 4). Dependencies are matched against
workspace members by normalised name (PEP 503), ignoring extras, markers and versions, and anything that isn't a
workspace member is ignored here (`bundle.py` reports it).

If the bundle isn't a workspace member, or has no `pyproject.toml`, the expected group is the `packages/*` members
alone and the check adds nothing: `bundle.py` already fails with its own message, and two messages about one cause
would be noise.

### D3. Move `normalise` and `requirement_name` into `release_config`

They live in `bundle.py`, which imports from `release_config`. They move to `release_config`, and `bundle.py` imports
them from there, keeping one definition and no import cycle. `bundle.py`'s tests keep passing unchanged, which is the
check that the move changed nothing.

### D4. Messages

- A bundled package outside the group:
  `troupe-runner-scripted isn't in the 'troupe' linked group in release-please-config.json, but troupe-run ships it:
  add it to its 'components'.`
- A `packages/*` member outside the group keeps today's message (`... isn't in the 'troupe' linked group in
  release-please-config.json: add it to its 'components'.`), so the existing test stays as it is.
- A component that's neither: `<name> is in the 'troupe' linked group in release-please-config.json, but troupe-run
  doesn't ship it: remove it.` This replaces "only packages/* members belong there". The protocol keeps its own
  message.

### D5. Showing a runner-only fix releases the bundle

The issue allows release-please's dry run or the config tests. The dry run needs the owner's GitHub token, which the
guard refuses an agent, and with nothing released yet it would release every component at 0.1.0 whatever the commit,
so it couldn't tell a runner-only fix apart. The proof is the config tests: the real config's group holds both runners
and the bundle, and removing a runner from it fails the check. That the group then releases together is
release-please's linked-versions behaviour, already relied on for the adapters. The owner can run the dry run with `!`
after the first release if they want to see it.

## Risks / Trade-offs

- [A core-only fix now bumps the runners' versions too, with empty changelog entries] → Accepted in #214: the bundle
  is the only way to install a runner, so separate versions gave users nothing.
- [The runners' planned move out gets one more step] → That change removes them from the bundle's dependencies, and
  the check then tells it to remove them from the group. `releasing.md` says so.
- [A bundled dependency added to `troupe-run` that's a workspace member under some third directory] → D1 covers it:
  membership comes from the dependency, not the directory.

## Migration Plan

None: no component has released. Rollback is reverting the commit; the manifest is untouched.
