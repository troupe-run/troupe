---
title: Install
description: Installing troupe.
status: written
prerelease: true
---

You install troupe with [uv](https://docs.astral.sh/uv/), from a release, the latest `main` or any commit. It takes
one command.

## Install the latest release

You need uv: [install it](https://docs.astral.sh/uv/getting-started/installation/) first if you don't have it. You
don't need Python: troupe needs Python 3.12 to 3.15, and uv downloads a version troupe supports if you don't have
one. troupe runs on Linux, macOS and Windows, all supported from the start and tested on every change.

Then install troupe:

<!-- x-release-please-start-version -->
```sh
uv tool install --no-sources "git+https://github.com/troupe-run/troupe@troupe-run-v0.1.0#subdirectory=packages/troupe-run"
```
<!-- x-release-please-end -->

And check it worked:

```sh
troupe --version
```

If your shell can't find `troupe`, run `uv tool update-shell` and open a new terminal.

The command installs `troupe-run`, troupe with the adapters and runners it comes with, from its release tag on
GitHub, and puts `troupe` on your path. [Your first theatre](first-theatre.md) sets up a theatre to run it in.

## Runners that come as extras

A runner that uses a client library for its engine comes as an extra of `troupe-run`, named after the runner, so an
install only carries the libraries of the runners you use. The command above installs every runner that needs nothing
more. To add a runner that comes as an extra, give its name in brackets, or `all` for every one:

<!-- x-release-please-start-version -->
```sh
uv tool install --no-sources "troupe-run[all] @ git+https://github.com/troupe-run/troupe@troupe-run-v0.1.0#subdirectory=packages/troupe-run"
```
<!-- x-release-please-end -->

| Extra | Installs |
|---|---|
| `all` | Every runner that comes as an extra. |
| `anthropic` | The Anthropic runner, which drives a model over the Anthropic Messages API, on [Claude's API](https://platform.claude.com/docs/en/api/messages) or a local engine that serves it, through the `anthropic` package. |

An actor on a runner you haven't installed is refused, and the message names the extra to install.

## Install another version

Each release is tagged `troupe-run-v<version>`, on [troupe's releases
page](https://github.com/troupe-run/troupe/releases): to install another one, give its tag in the command above.
`--no-sources` installs each part of troupe at the version the release names.

To install the latest `main` or a particular commit, give it in place of the tag, and leave out `--no-sources` so
every part comes from that commit:

```sh
uv tool install "git+https://github.com/troupe-run/troupe@<commit>#subdirectory=packages/troupe-run"
```

## Upgrade and uninstall

- **Upgrade** to a newer release by running the install command again with its tag. It replaces what you have.
  `uv tool upgrade troupe-run` leaves a release where it is, since the tag names it exactly. It does move an install
  of `main` to the latest `main`.
- **Uninstall** with `uv tool uninstall troupe-run`.

## What's decided

- **Releases are installed with uv, from GitHub.** troupe isn't on PyPI, and may never be
  ([#139](https://github.com/troupe-run/troupe/issues/139)). A release is installed by the tag of `troupe-run`, the
  package the command installs: `troupe-run-v<version>`. How troupe reaches people who won't use uv is open, in
  [#143](https://github.com/troupe-run/troupe/issues/143).
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
