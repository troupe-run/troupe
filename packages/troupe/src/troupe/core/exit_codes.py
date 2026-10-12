"""Every exit code the CLI can return.

This is the only place they are defined. docs/cli/exit-codes.md mirrors it, checked by a test.
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
    CANCELLED = 130
    """A person cancelled the command with Ctrl-C (128 + SIGINT, on every platform), and what it
    was doing stopped cleanly. For perform, the run's end is recorded as cancelled."""
