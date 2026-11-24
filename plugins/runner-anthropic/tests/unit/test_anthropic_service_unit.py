"""How the module that uses the anthropic package keeps the library's own logging out of the run's
output: a debug record asked for reaches neither standard output nor standard error, and a
warning reaches the runner's stream as one line, masked and cut (spec: anthropic-runner, "The
library's own logging stays out of the run's output").

Its tests that start a process, open a socket or use a git theatre are in
integration/test_anthropic_service.py."""

import io
import logging
import sys
from collections.abc import Iterator

import pytest

from anthropic_service_shared import (
    KEY,
    clean_environment_fixture,  # noqa: F401
)
from troupe_runner_anthropic.defaults import (
    LIBRARY_LOG_MAX_BYTES,
)
from troupe_runner_anthropic.masking import MASK, Mask
from troupe_runner_anthropic.service import (
    LIBRARY_LOGGERS,
    quiet_library_logging,
)

# Requirement: The library's own logging stays out of the run's output


@pytest.fixture
def library_loggers() -> Iterator[None]:
    """Each library logger's handlers, level and propagation, restored after the test."""
    saved = [
        (logger, list(logger.handlers), logger.level, logger.propagate)
        for logger in (logging.getLogger(name) for name in LIBRARY_LOGGERS)
    ]
    yield
    for logger, handlers, level, propagate in saved:
        logger.handlers = handlers
        logger.setLevel(level)
        logger.propagate = propagate


@pytest.mark.usefixtures("library_loggers")
def test_a_debug_record_asked_for_reaches_neither_standard_output_nor_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # What ANTHROPIC_LOG=debug does: the library's logger at DEBUG, with a handler that prints.
    library = logging.getLogger("anthropic")
    library.setLevel(logging.DEBUG)
    library.addHandler(logging.StreamHandler(sys.stdout))
    stream = io.StringIO()
    quiet_library_logging(Mask(KEY), stream)
    library.debug("Request options: %s", {"headers": {"Authorization": f"Bearer {KEY}"}})
    logging.getLogger("anthropic._base_client").info("HTTP Request: POST")
    logging.getLogger("httpx2").debug("sending")
    assert stream.getvalue() == ""
    assert capsys.readouterr().out == ""


@pytest.mark.usefixtures("library_loggers")
def test_a_warning_reaches_the_stream_as_one_line_masked_and_cut(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stream = io.StringIO()
    quiet_library_logging(Mask(KEY), stream)
    logging.getLogger("anthropic._client").warning("key %s\nthen %s", KEY, "x" * 5000)
    written = stream.getvalue()
    assert written.count("\n") == 1
    assert written.startswith("anthropic runner: library warning: key ")
    assert MASK in written
    assert KEY not in written
    assert written.rstrip("\n").endswith("bytes left out)")
    assert len(written.encode()) < LIBRARY_LOG_MAX_BYTES + 200
    assert capsys.readouterr().out == ""
