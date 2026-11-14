"""What the runner sets around the anthropic package without importing it (anthropic-runner design
D4, D11): the environment the library would read, and its loggers. Kept apart from service.py, the
one module that imports the library, so the runner can answer its handshake before the library's
slow import (about two seconds) has run.
"""

import logging
import os
import sys
from collections.abc import Callable
from typing import Final, Protocol

from troupe_runner_anthropic.defaults import LIBRARY_LOG_MAX_BYTES

LIBRARY_PREFIX: Final = "ANTHROPIC_"
"""The prefix of every environment variable the library reads (design D4)."""

LIBRARY_LOGGERS: Final = ("anthropic", "httpx2", "httpcore2")
"""The library's loggers, and its HTTP client's."""


def clear_library_environment(
    environ: dict[str, str] | os._Environ[str] | None = None,
) -> list[str]:
    """Remove every ANTHROPIC_* variable from ``environ`` (the process's own by default), so the
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
            self._stream.write(f"anthropic runner: library {record.levelname.lower()}: {text}\n")
            self._stream.flush()
        except Exception:  # logging must never fail the run
            self.handleError(record)


def quiet_library_logging(mask: Callable[[str], str], stream: Writable | None = None) -> None:
    """Keep the library's loggers off standard output: warnings and above to ``stream`` (standard
    error), masked and cut, and nothing below them, whatever ANTHROPIC_LOG asked for."""
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
