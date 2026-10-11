"""Failures the platform seam reports.

troupe.core turns each into a TroupeError with a code, the problem and the fix.
"""

from pathlib import Path


class PlatformError(Exception):
    """Base class: an OS-level operation could not be completed."""


class LockTimeoutError(PlatformError):
    def __init__(self, lock_path: Path, waited: float) -> None:
        super().__init__(f"timed out after {waited:.1f}s waiting for {lock_path}")
        self.lock_path = lock_path
        self.waited = waited


class LockAlreadyHeldError(PlatformError):
    def __init__(self, lock_path: Path) -> None:
        super().__init__(f"this process already holds {lock_path}")
        self.lock_path = lock_path


class FileInUseError(PlatformError):
    def __init__(self, path: Path, waited: float) -> None:
        super().__init__(f"{path} is held open by another process (waited {waited:.1f}s)")
        self.path = path
        self.waited = waited
