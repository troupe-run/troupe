"""What the runner sets around the openai package without importing it (openai-library design D2,
D9): the environment the library would read, and its loggers. Kept apart from service.py, the
one module that imports the library, so the runner can answer its handshake before the library's
slow import (more than a second) has run.
"""

import logging
import os
import sys
from collections.abc import Callable
from typing import Final, Protocol

from troupe_runner_openai.defaults import LIBRARY_LOG_MAX_BYTES

LIBRARY_PREFIX: Final = "OPENAI_"
"""The prefix of every environment variable the library reads, OPENAI_LOG included, which it reads
as it's imported (design D2, D9)."""

LIBRARY_LOGGERS: Final = ("openai", "httpx2", "httpcore2")
"""The library's loggers, and its HTTP client's."""


def clear_library_environment(
    environ: dict[str, str] | os._Environ[str] | None = None,
) -> list[str]:
    """Remove every OPENAI_* variable from ``environ`` (the process's own by default), so the
    library can't read one; the names removed."""
    target = os.environ if environ is None else environ
    names = sorted(name for name in target if name.upper().startswith(LIBRARY_PREFIX))
    for name in names:
        del target[name]
    return names


class Writable(Protocol):
    """Where the library's warnings go: standard error, as text."""

    def write(self, text: str, /) -> int: ...

    def flush(self) -> None: ...


class _CutHandler(logging.Handler):
    """Writes a record's message to a text stream, one line, cut to LIBRARY_LOG_MAX_BYTES."""

    def __init__(self, stream: Writable, mask: Callable[[str], str]) -> None:
        super().__init__(logging.WARNING)
        self._stream = stream
        self._mask = mask

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = " ".join(self.format(record).split())
            data = self._mask(text).encode("utf-8", "backslashreplace")
            if len(data) > LIBRARY_LOG_MAX_BYTES:
                left = len(data) - LIBRARY_LOG_MAX_BYTES
                text = data[:LIBRARY_LOG_MAX_BYTES].decode("utf-8", "ignore")
                text += f"… ({left} bytes left out)"
            else:
                text = data.decode("utf-8")
            self._stream.write(f"openai runner: library {record.levelname.lower()}: {text}\n")
            self._stream.flush()
        except Exception:  # logging must never fail the run
            self.handleError(record)


def quiet_library_logging(mask: Callable[[str], str], stream: Writable | None = None) -> None:
    """Keep the library's loggers off standard output: warnings and above to ``stream`` (standard
    error), masked and cut, and nothing below them, whatever OPENAI_LOG asked for."""
    handler = _CutHandler(sys.stderr if stream is None else stream, mask)
    for name in LIBRARY_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.setLevel(logging.WARNING)
        logger.propagate = False


__all__ = [
    "LIBRARY_LOGGERS",
    "LIBRARY_PREFIX",
    "Writable",
    "clear_library_environment",
    "quiet_library_logging",
]
