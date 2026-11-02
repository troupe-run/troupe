# Design

## Context

See proposal.md, "Why", for the failure and its cause. Constraints that shape the fix:

- `.github/dependabot.yml` is generated in troupe-run/infrastructure (`tofu/dependabot.json`, rendered by
  `scripts/dependabot_config.py`) and delivered by its App. The guard refuses a commit to it here. The generator has no
  way to declare an ignore today.
- Dependabot reads the root `pyproject.toml` and every member's, so it sees each member as a dependency of the
  workspace: of the root's `dev` group, and of `troupe-run`'s pins. It looks each name up on PyPI. Only `troupe`
  exists there now, owned by someone else. The rest return 404 and are skipped ("Latest version is" empty).
- The workspace member always wins locally, so no lock file Dependabot could write would ever move a member. Even
  where PyPI's version matched ours, the update would be a no-op at best.

## Goals / Non-Goals

**Goals:**

- Dependabot's `uv` job in troupe stops trying to move a workspace member, now and for members added later.
- A member that the delivered ignores don't cover fails troupe's check, rather than failing next Monday's Dependabot
  run silently. Before this change, that failure only appeared in a job log nobody was watching (#254).

**Non-Goals:**

- Publishing to PyPI or claiming names there (#208 decides how troupe installs). See D1.
- Changing what Dependabot does for real dependencies. Every other dependency keeps its weekly updates and cooldowns.

## Decisions

### D1. Ignore the members in Dependabot, rather than change how they're found

Dependabot's `ignore` with a `dependency-name` and no `versions` or `update-types` stops all version updates for that
name, which is exactly "never propose a version for a member".

Alternatives considered:

- **`exclude-paths: packages/troupe-run`**, as #254 first suggested. It doesn't help: the root's `dev` group names
  `troupe` too, and the failure predates the bundle.
- **Register the names on PyPI.** `troupe` belongs to an active, unrelated project, and PEP 541 transfers only
  abandoned names. For the free names, a published version equal to ours would make Dependabot report nothing to
  update, but any newer one would fail the same way. It's a release decision, outside this change.
- **Rename `troupe`.** It costs far more than this bug is worth, and the next collision would bring it back.

### D2. Wildcards in the policy, not an exact list

infrastructure's policy ignores `troupe` and `troupe-*` for troupe's `uv` entry. A new member named `troupe-<x>` is
covered with no edit in infrastructure, and so is a squatter on any `troupe-*` name, which would otherwise start
failing the job the day it's published. Ignoring a third party's `troupe-*` package costs nothing, because troupe
depends on none.

The policy's shape (a per-repository, per-ecosystem list of names, rendered as `ignore: - dependency-name: …`) is
infrastructure#259's to design. This change relies only on the delivered file containing those two names in its
`uv` entry for `/`.

### D3. troupe checks the delivered file, not infrastructure's policy

The check reads `.github/dependabot.yml` in the checkout. That's the file Dependabot reads, it's always present
locally, and reading it needs no network or second repository. The check doesn't care how infrastructure produces the
ignores, only that they cover every member.

### D4. Matching follows Dependabot and packaging

- Both names are normalised as PEP 503 does (`release_config.normalise`), as Dependabot does for Python names.
- `*` is the only wildcard and matches any run of characters, including none. Every other character is literal. The
  pattern is built with `re.escape` around the `*`s, not `fnmatch`, which would also treat `?` and `[` as wildcards.
- Only ignores with neither `versions` nor `update-types` count. One that ignores only some updates still lets
  Dependabot try the others, which is the failure (spec scenario "An ignore that covers only some versions").
- No `uv` entry for `/`, a missing file or YAML that won't parse is a problem the check reports, never a pass. A
  malformed input is an error, not a fall-through.

### D5. Where the check lives

A new `scripts/dependabot_members.py` exposes `problems(root) -> list[str]`, like `scripts/bundle.py`. The members come
from `release_config.members`, so no package path is written into the module (a `packages/<name>` literal would widen
which suites reach it). Its tests go in `scripts/tests/workspace/test_dependabot_members.py`. They break a copy of the
real files one property at a time (the `test_bundle.py` pattern), and end with one test on the real repository.
`.github/dependabot.yml` is in no scope in `scripts/check-paths.toml`, so a delivery that changes it runs the full
check.

Messages name the member, the file, and the fix: "add it to the uv ignores in troupe-run/infrastructure's Dependabot
policy (tofu/dependabot.json)".

## Risks / Trade-offs

- [The troupe check fails until infrastructure delivers the ignore] → Write the check first and show it failing on
  today's file (task 1.1), which proves it catches #254. Then merge and apply infrastructure#259, and rebase this
  branch on the delivery commit before the PR is marked ready (tasks 3.1, 3.2).
- [Dependabot's wildcard behaviour differs from D4's] → GitHub documents `*` in `dependency-name`. The run after
  delivery is the real test (task 4.2): its log must show no "Checking if troupe … needs updating" leading to an
  update, and no `dependency_file_not_resolvable`.
- [A later infrastructure edit drops the ignore] → troupe's check fails on the delivery commit's push to `main`, naming
  each uncovered member.

## Migration Plan

1. This branch: the check and docs, the check failing on today's file.
2. infrastructure#259: the policy declares the ignores, the generator renders them, apply delivers troupe's file.
3. This branch: rebase on `main` with the delivered file. The check passes, and CI passes.
4. Once the ignore is on `main`: ask the owner to run Dependabot's "Check for updates" for `uv` in troupe (or wait for Monday's
   run), and read its log as task 4.2 says.

Rollback: revert the infrastructure policy change and this PR together. Reverting only infrastructure's fails troupe's
check, which is the intent.
