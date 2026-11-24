"""troupe init writes its printed steps for PowerShell on Windows and for a POSIX shell everywhere
else (spec: cli; init-and-audition design D4, D8, D9).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_cli_init.py."""

import sys

from troupe.cli import init as init_cli


def test_the_shell_is_powershell_on_windows_and_posix_elsewhere() -> None:
    expected = init_cli.POWERSHELL if sys.platform == "win32" else init_cli.POSIX
    assert init_cli.SHELL is expected
