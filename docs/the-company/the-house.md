---
title: The house (daemon)
description: The local daemon.
status: written
prerelease: true
---

The house is troupe's long-lived local process. It isn't built yet
([#63](https://github.com/troupe-run/troupe/issues/63)): today each command does its own work and stops. This is
what's decided about it.

## What it does

- **It's the only orchestrator.** Every troupe command, whether it changes something or only reads, goes through the
  house. The command line, a terminal UI and a web UI are all clients of it, so they can't behave differently. Only
  the commands that need no theatre and manage the house itself skip it: `--version`, `--help`, and starting,
  stopping and checking the house.
- **It supervises runs** beyond the terminal that started them, so closing your terminal doesn't end a run.
- **It works when nobody's at a terminal,** so [gates](gates-and-decisions.md), cues and notifications can reach
  whoever owns a decision.
- **Your history stays the truth.** The house holds nothing it can't rebuild from your theatre's events, and it
  notices changes it didn't make, such as a git `pull`, `merge` or `checkout`.

## One per user

The house runs as you, with your permissions and your environment, and runs actors as you. Each person on a computer
has their own house, which never reaches into anyone else's files. Your git identity and credentials are your own.

## Starting and stopping

- **troupe starts it for you.** When a command needs the house and it isn't running, the command starts it, and says
  so: it never starts silently.
- **You can start and stop it yourself,** with `troupe house start` and `troupe house stop`, and see it with
  `troupe house status`. These names aren't final.
- **You'll be able to turn auto-start off** ([#118](https://github.com/troupe-run/troupe/issues/118)). Then a command
  that needs the house, while it isn't running, refuses and tells you to run `troupe house start`.
- **The command line and the house are installed together, as one unit,** so their versions always match.

## Its own settings

The house keeps its own settings and history in your home directory, in `~/.troupe/`
(`%USERPROFILE%\.troupe\` on Windows), with its own schema. Set `TROUPE_HOME` to keep them somewhere else. A
theatre's config never comes from there: it lives only in the theatre.

## The web

A web UI reaches the house through a separate, small web gateway that runs on your computer, as a client of the
house like the command line ([#64](https://github.com/troupe-run/troupe/issues/64)). It listens only on your own
computer, needs a token for each session, and refuses any request that fails its checks. Updates are pushed to the
page as they happen, never polled. Policy never travels with a request, so no client can loosen it.

## Still open

What happens to running actors when the house stops or crashes, whether stopping it is refused while runs are going,
and how it behaves in CI are details of its design, in [#63](https://github.com/troupe-run/troupe/issues/63).
