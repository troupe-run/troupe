"""Every exit code the CLI can return.

This is the only place they are defined. The exit-code table in docs/prompt-book/cli.md is
generated from these members and their docstrings (scripts/docs_reference.py).
Later changes add codes here and nowhere else.
"""

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    """The command completed."""
    FAILURE = 1
    """The command could not complete. The error says why and what to do."""
    USAGE = 2
    """The command line was not understood: an unknown command or flag, or a malformed value."""
    WOULD_CHANGE = 3
    """A rehearsal (`--rehearse`) found that the command would succeed and change something: record
    a change, write a file, or start a run. A rehearsal with nothing to do exits 0, and one that
    would be refused exits with the refusal's own code, so CI can tell the three apart."""
    CANCELLED = 130
    """You cancelled the command with Ctrl-C, and it stopped cleanly: `troupe perform` records the
    run as `cancelled`. 130 is the shell's code for an interrupt (128 + SIGINT), and troupe uses it
    on every platform."""
