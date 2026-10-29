---
title: Install
description: Installing troupe.
status: written
prerelease: true
---

troupe hasn't had a release yet, but you can install the latest `main`, or any commit, with
[uv](https://docs.astral.sh/uv/), and run an actor with it.

## Install with uv

troupe needs Python 3.12 to 3.15, on Linux, macOS or Windows. All three are supported from the start, and tested on
every change. You don't need to install Python yourself: uv downloads a version troupe supports if you don't have one.

```sh
uv tool install "git+https://github.com/troupe-run/troupe@main#subdirectory=packages/troupe-run"
```

This installs the latest `main`. To install a particular commit instead, give the commit in place of `main`:

```sh
uv tool install "git+https://github.com/troupe-run/troupe@<commit>#subdirectory=packages/troupe-run"
```

It installs `troupe-run`: troupe, with the adapters and runners it comes with, all from that one commit. It puts
`troupe` on your path. Check it worked:

```sh
troupe --version
```

If your shell can't find `troupe`, run `uv tool update-shell` and open a new terminal.

- **Upgrade** an install of `main` to the latest `main` with `uv tool upgrade troupe-run`. To move to another commit,
  run the install command again with that commit.
- **Uninstall** with `uv tool uninstall troupe-run`.

[Your first theatre](first-theatre.md) sets up a theatre to run it in.

## What's decided

- **Releases are installed with uv, from GitHub.** troupe isn't on PyPI, and may never be
  ([#139](https://github.com/troupe-run/troupe/issues/139)). Installing a release by its tag comes with the first
  release ([#189](https://github.com/troupe-run/troupe/issues/189)). How troupe reaches people who won't use uv is
  open, in [#143](https://github.com/troupe-run/troupe/issues/143).
- **Each release is on GitHub**, at [troupe's releases page](https://github.com/troupe-run/troupe/releases), with
  its [changelog](../backstage/changelog.md).
- **The command line and the house are installed and upgraded together, as one unit,** so they never disagree
  about versions. The [house](../the-company/the-house.md) is troupe's long-lived local process.
- **troupe keeps its own state in your home directory,** in `~/.troupe/` (`%USERPROFILE%\.troupe\` on Windows).
  Set `TROUPE_HOME` to keep it somewhere else.

## Running it from a clone

To work on troupe itself, run it from a clone of its repository instead:

```sh
git clone https://github.com/troupe-run/troupe.git
cd troupe
uv run troupe --version
```

From there, `uv run troupe` runs troupe from the clone.
