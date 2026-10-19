---
title: Install
description: Installing troupe.
status: written
prerelease: true
---

troupe hasn't had a release yet, so there's nothing to install. How a release will be installed isn't decided yet:
whether as a package for `uv tool`, a standalone executable or a Homebrew formula, and whether it can rely on `uv`
being there, is an open question in [#38](https://github.com/troupe-run/troupe/issues/38).

What is decided:

- **Each release is on GitHub**, at [troupe's releases page](https://github.com/troupe-run/troupe/releases), with
  its [changelog](../backstage/changelog.md).
- **troupe needs Python 3.12 to 3.15**, on Linux, macOS or Windows. All three are supported from the start, and
  tested on every change.
- **The command line and the house are installed and upgraded together, as one unit,** so they never disagree
  about versions. The [house](../the-company/the-house.md) is troupe's long-lived local process.
- **troupe keeps its own state in your home directory,** in `~/.troupe/` (`%USERPROFILE%\.troupe\` on Windows).
  Set `TROUPE_HOME` to keep it somewhere else.

## Trying it before a release

You can run troupe from a clone of its repository, with [uv](https://docs.astral.sh/uv/):

```sh
git clone https://github.com/troupe-run/troupe.git
cd troupe
uv run troupe --version
```

From there, `uv run troupe` runs troupe from the clone. [Your first theatre](first-theatre.md) sets one up.
