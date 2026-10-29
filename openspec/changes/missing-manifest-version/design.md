# Design

## Context

See proposal.md, "Why". `release_config.problems` builds the two messages separately: one in the member loop of
`problems` (`'{path} ({name}) has no version in {MANIFEST}: add "{path}": "0.0.0".'`) and one in
`_protocol_problems`. When the protocol is missing from the manifest, `_record_problems` already says nothing (it has
no version to compare the record with), so only the missing-entry message reaches the user.

release-please tags each component `<component>-v<version>` (`include-component-in-tag: true`). A member's component
is its project name, which the check already requires its config entry to use, so `plugins/runner-scripted` is tagged
`troupe-runner-scripted-v*`. The protocol's component is `protocol`. No tags exist yet: #89 hasn't merged.

The check is standard-library only and runs as a test inside `scripts/check.py`, on every commit and in CI. CI's
check legs check out with `actions/checkout`'s default depth of 1, which fetches no tags.

## Goals / Non-Goals

**Goals:**
- Neither message suggests a version the check can't know.
- Each message names the component's tag pattern and a command that finds its latest tag, so the fix is one step.
- Both messages come from one helper, so the wording is decided in one place.

**Non-Goals:**
- Reading tags, or checking that a manifest version matches the latest tag. That needs the tags, which CI's checkout
  and many clones don't have (D1).
- Changing any other message, or what the check compares.

## Decisions

### D1. The check names where to find the version; it doesn't read tags

The message names the tag pattern and the command that lists those tags on `origin`. The check itself runs no git
command. This settles the open question in #197.

*Alternative:* read the latest `<component>-v*` tag with `git tag` and put its version in the message. Rejected:
- CI's checkout and a shallow or fresh clone have no tags, so the check would find none and fall back to `0.0.0`. That
  is the same guess this change removes, made quietly, and wrong in exactly the case #197 is about.
- It would make the check depend on git and on the state of the clone, where today it reads three files.
- Telling "no tags fetched" apart from "never released" needs the network (`git ls-remote`), which the check must not
  need: it runs offline, before every commit.

### D2. The command queries `origin`, sorted newest first

The message names `git ls-remote --tags --sort=-v:refname origin '<component>-v*'`. It asks `origin` rather than the
local clone, so it gives the right answer even when the clone hasn't fetched tags, and `-v:refname` puts the newest
version first (so `0.10.0` sorts above `0.9.0`). `ls-remote` matches the pattern against the end of the ref name, so
`troupe-v*` doesn't match `troupe-runner-scripted-v0.1.0`.

*Alternative:* `git tag --list '<component>-v*' --sort=-v:refname`. Rejected: it reads local tags only, so in a clone
that hasn't fetched them it prints nothing, which reads as "never released".

### D3. Wording

One helper, `_missing_version(path, component)`, returns both messages:

```
plugins/runner-scripted (troupe-runner-scripted) has no version in .release-please-manifest.json: add
"plugins/runner-scripted" at the version it last released, its latest troupe-runner-scripted-v<version> tag
(`git ls-remote --tags --sort=-v:refname origin 'troupe-runner-scripted-v*'`), or at "0.0.0" if it has none.
```

The protocol's message is the same with `protocol` as both the path and the component, and without the parenthesised
name (as today). A member's component is its project name even when its config entry is missing or wrong, since the
check already tells you to set `component` to it.

## Risks / Trade-offs

- [The command needs the network and a remote named `origin`] → It's the human's fix, not the check's, and the
  message shows the whole command, so another remote name is an obvious edit.
- [Single quotes don't quote in Windows `cmd.exe`] → They do in PowerShell, Windows' default shell, and in every
  POSIX shell. Without them, zsh refuses an unmatched glob. Quotes are the better default.
- [Someone still restores `0.0.0` after a release] → The check doesn't catch it (Non-Goals). The message now tells
  them what to restore instead of telling them to do this.
- [The command's behaviour is assumed] → Task 1.1 checks it against a local bare repository with tags that sort
  differently by version than by text, and with a `troupe-v*` and a `troupe-runner-scripted-v*` tag side by side.
