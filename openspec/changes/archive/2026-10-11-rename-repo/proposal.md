# Proposal

Issue: troupe-run/troupe.run#26 (troupe-run/troupe#26 once renamed)

## Why

The product repo is called `troupe-run/troupe.run`, which reads as the website's domain rather than the product. It
should be `troupe-run/troupe`: the troupe product, from the troupe-run org. It is day 1, with two archived changes and
a handful of links, so the rename is cheap now and only gets dearer. Doing it before `troupe-run/infrastructure`
adopts the org (#19) means that work adopts the repo under its final name. Every reference is updated rather than
left to GitHub's redirects. A redirect breaks as soon as anything else claims the old name, and it hides stale links
rather than fixing them.

## What Changes

- **The repo is renamed on GitHub** to `troupe-run/troupe`, just before this change's PR, so the new URLs are live
  when the PR lands.
- **Every live reference in this repo names the new repo:**
  - `BUG_REPORT_URL` in `packages/troupe/src/troupe/core/errors.py` (users see it in internal-error messages) and the
    test that checks it, `packages/troupe/tests/test_cli.py`;
  - the `Repository` URL in `packages/troupe/pyproject.toml`;
  - the links in `packages/troupe/README.md`, `plugins/README.md` and `protocol/README.md`;
  - the fixture in `scripts/tests/test_guard_claude.py`, changed to a repo that is actually different from this one
    (see design);
  - the title of `CLAUDE.md` (`# troupe.run`, the repo's old name).
  References to the domain `https://troupe.run` (README, `Homepage`, the protocol schema `$id`) stay as they are.
- **Other repos in the org** get their own PRs, each citing #26:
  - the website, `troupe-run/troupe-run.github.io`: its 16 references, including the "Watch on GitHub" links, the
    e2e test, the link checker's skip and its CONTRIBUTING;
  - the org profile, `troupe-run/.github`: `profile/README.md` links the repo as "troupe.run repository". The issue
    doesn't name it, but it is a live reference.
- **Open issue bodies** that name the repo are edited to the new name: #19 and #25 (#26 itself is left as the record of
  the rename).
- **The two GitHub Apps are confirmed** to still cover the renamed repo: the DCO app and the
  `troupe-run-infrastructure` App installation.
- **The local workspace follows the rename:** the clone's `origin` URL, the folder
  `~/Projects/troupe/troupe.run` → `~/Projects/troupe/troupe`, and Claude Code's per-folder state for it (session
  history, project memory, the project's settings entry and prompt history), plus the memory's own text. The
  virtual environment is rebuilt, because its scripts hard-code the folder path.

Out of scope:
- **Archived OpenSpec changes** (`openspec/changes/archive/`) keep `troupe-run/troupe.run`. They record what was
  true when they were written, and their `Issue:` lines still resolve through GitHub's redirect for issue numbers.
  Rewriting them would make history claim a name it never had.
- **The brand and the domain:** `troupe` and `https://troupe.run` are unchanged.
- **The owner's loose notes** in `~/Projects/troupe/` (`NEXT.md`, `*-kickoff.md`). They aren't in any repo and
  already describe the rename. They are the owner's to edit.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
None. No spec names the repo, and no requirement changes. Users see a different URL in internal-error messages, but
the behaviour is the same, so the change sets `skip_specs: true`. Errors pointing at the issue tracker is current
behaviour that no spec states yet. Specifying it is a separate change, not part of a rename.

## Impact

- **Code:** one constant and its test, one packaging URL, one guard-test fixture. No API or dependency changes.
- **Docs:** three package READMEs and `CLAUDE.md`.
- **GitHub:** the repo's name and URLs (old URLs redirect, but nothing of ours relies on that); two follow-on PRs in
  other org repos; two issue bodies.
- **Local:** the clone's path changes. Anything else keyed by the old path (the venv, Claude Code's per-folder state)
  must move with it, or it will silently start fresh.
