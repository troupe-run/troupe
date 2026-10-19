---
title: Exit codes
description: Every exit code troupe can return.
status: written
prerelease: false
---

Every exit code `troupe` can return. The table is checked against the code (`troupe.core.exit_codes.ExitCode`)
by a test, so it can't drift. When a command fails, standard output is empty and standard error says what went
wrong and how to fix it.

| Code | Name | Meaning |
|---|---|---|
| 0 | `OK` | The command completed. |
| 1 | `FAILURE` | The command could not complete. The error says why and what to do. |
| 2 | `USAGE` | The command line was not understood: an unknown command or flag, or a malformed value. |
| 130 | `CANCELLED` | You cancelled the command with Ctrl-C, and it stopped cleanly: `troupe perform` records the run as `cancelled`. 130 is the shell's code for an interrupt, and troupe uses it on Windows too. |
