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


class CommandNotFoundError(PlatformError):
    def __init__(self, command: str) -> None:
        super().__init__(f"command not found: {command!r}")
        self.command = command


class LineTooLongError(PlatformError):
    def __init__(self, limit: int) -> None:
        super().__init__(f"a line of output was longer than the limit of {limit} bytes")
        self.limit = limit


class EnvironmentPolicyError(PlatformError):
    def __init__(self, name: str, reason: str) -> None:
        super().__init__(f"environment variable {name!r}: {reason}")
        self.name = name
        self.reason = reason
