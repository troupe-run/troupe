"""Making a directory link in a test, on every platform (runner-sdk design, Risks).

A symbolic link needs a privilege on Windows that CI's runner may lack, so on Windows the link is a
directory junction, which needs none. Path.resolve follows both, so the link-escape tests run on all
three platforms rather than being skipped."""

import os
import sys
from pathlib import Path


def link_directory(link: Path, target: Path) -> None:
    """Make ``link`` a directory link to ``target``."""
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)
