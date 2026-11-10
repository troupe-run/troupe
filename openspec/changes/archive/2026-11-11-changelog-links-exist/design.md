# Design

## Context

See proposal.md for why. The page and its test came from user-docs design D4: the page links the changelogs and
doesn't copy them, and the test compares the page's set of `CHANGELOG.md` links with the packages in
`release-please-config.json`. Today that's an exact match, made without looking at the files.

Some things about how releases work shape this design:

- A release pull request changes `CHANGELOG.md` and `pyproject.toml` files. No scope in `scripts/check-paths.toml`
  covers those, so it runs the full check, this test included.
- Only the release App may commit to a `release-please--*` branch. The releases spec fails the guard on a commit by
  anyone else.
- Open release pull request #263 makes the first release of `troupe-runner-ollama`, `troupe-runner-openai` and
  `troupe-plugin-sdk`, and writes their changelogs.

## Goals / Non-Goals

**Goals:**

- No link on the page is a 404 on `main`.
- Every part release-please releases still appears on the page, so adding a part to the config without adding it
  to the page still fails.

**Non-Goals:**

- Checking other GitHub links from `docs/` (website#112's build check does that for the whole site).
- Linking a changelog automatically when it's first written.

## Decisions

### D1. An unreleased part is a list item that starts with its component name in code

```markdown
- `troupe-runner-ollama`
```

The test finds a named part by a list item that starts with `` `<component>` ``. A bare mention doesn't count:
`` `troupe-run` `` and `` `troupe-plugin-sdk` `` already appear in the page's prose, so a code span alone would pass
a page that had dropped the part's entry. A list item keeps unreleased parts in the same lists as the linked ones,
where readers look for them. The page's existing sentences ("changelogs start with their first releases") stay, and
explain why there's no link.

The name comes from each package's `component` in `release-please-config.json`. That's the name in its release tag,
and the link text the page already uses. Every package sets it. If one didn't, the test would fail, naming the
package, instead of guessing a name from its path.

Alternatives: matching the link text of linked parts too. Not needed: a linked part is found by its path, and the
link text isn't what goes wrong. Linking the part's directory instead of naming it: every entry would then resolve,
but the issue asks for a name, and a directory isn't a changelog.

### D2. Existence is read from the working tree

A linked changelog has to exist at `<repo>/<path>`. `problems()` takes a callable that says whether a path exists.
The real test passes one that checks the repository, and the unit tests pass a set. This keeps the sample-based
tests (a misnamed changelog, a custom `changelog-path`) independent of which parts have been released.

### D3. A named part whose changelog exists passes (owner's decision on #366's proposal)

The issue proposed failing until the page links a new changelog. That deadlocks a first release:

- The release pull request writes the changelog, so it would fail.
- Only the release App can push to that pull request, so nobody can add the link there.
- A pull request on `main` that adds the link fails too, because `main` doesn't have the file yet.

So that case passes, and a pull request after the release links the changelog.

Alternatives considered:

- **Exempt release branches.** The test would read the head branch from CI's environment. The merge queue's
  `merge_group` run has no head ref, so the release pull request would still fail when it's queued.
- **Link the directory until release.** See D1.

### D4. Failure messages name the fix

Each problem names the page and the path or part, and says what to do:

- A link release-please doesn't write: unchanged, it lists the changelogs release-please writes.
- A link to a changelog that doesn't exist: name the part as `` - `<component>` `` until its first release.
- A part the page doesn't show: link `<path>`, or, before its first release, name it as `` - `<component>` ``.

## Risks / Trade-offs

- [After a first release, the page names a part whose changelog exists until someone links it] → No 404 results,
  and the page's wording says the changelog starts with the first release. Linking it is a docs pull request after
  the release merges. Tasks record the one this change creates (#263's parts). Owner accepted the trade-off.
- [The test reads files outside `docs/`] → `CHANGELOG.md` files are in no scope in `scripts/check-paths.toml`, so
  any change to them runs the full check, and this test with it. A docs-only change runs the docs tests, which read
  the tree as it is.

## Migration Plan

When this merges, the page's links depend on whether #263 has merged:

- **#263 has merged:** all three changelogs exist, and the page keeps its links.
- **#263 hasn't merged:** the page names the three parts, and the issue for the follow-up says to link them once
  #263 merges.
