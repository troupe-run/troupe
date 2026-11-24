"""What the runner sets around the openai package (openai-library design D11): every variable the
library reads is removed from the environment and nothing else, the library's warnings reach
standard error masked and cut with nothing below a warning, and a status failure keeps its
headers by lower-case name (spec: openai-runner, "The library finds nothing of its own", "The
library's own logging stays out of the run's output").

Its tests that start a process, open a socket or use a git theatre are in
integration/test_openai_library.py."""

import io
import logging

from openai_harness import CANARY
from openai_library_shared import LIBRARY_VARIABLES
from troupe_runner_openai.defaults import LIBRARY_LOG_MAX_BYTES
from troupe_runner_openai.failures import StatusError
from troupe_runner_openai.library import clear_library_environment, quiet_library_logging

# What the runner sets around the library (library.py, failures.py)


def test_every_variable_the_library_reads_is_removed_and_nothing_else() -> None:
    environ = {**LIBRARY_VARIABLES, "OPENAI_LOG": "debug", "HTTPS_PROXY": "http://p:1", "PATH": "x"}
    removed = clear_library_environment(environ)
    assert removed == sorted([*LIBRARY_VARIABLES, "OPENAI_LOG"])
    assert environ == {"HTTPS_PROXY": "http://p:1", "PATH": "x"}


def test_the_librarys_warnings_reach_standard_error_masked_and_cut_and_nothing_below() -> None:
    out = io.StringIO()
    quiet_library_logging(lambda text: text.replace(CANARY, "[credential]"), out)
    logger = logging.getLogger("openai")
    logger.debug("Request options: Authorization: Bearer %s", CANARY)
    logger.info("HTTP Request: POST")
    logger.warning("retrying with %s and %s", CANARY, "x" * (LIBRARY_LOG_MAX_BYTES * 2))
    written = out.getvalue()
    assert written.count("\n") == 1
    assert written.startswith("openai runner: library warning: retrying with [credential]")
    assert written.rstrip().endswith("bytes left out)")
    assert CANARY not in written
    assert "Authorization" not in written


def test_a_status_failure_keeps_its_headers_by_lower_case_name() -> None:
    failure = StatusError(429, {"Retry-After": "2"}, b"{}")
    assert failure.headers == {"retry-after": "2"}
