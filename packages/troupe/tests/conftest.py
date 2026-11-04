"""A test of core's fails when it leaves the Claude Code runner's stand-in claude running
(reap-fake-claude design D3). Only re-exports, so it's left out of mypy (pyproject.toml)."""

import claude_stand_in

_guard = claude_stand_in.stand_in_guard()
pytest_configure = _guard.pytest_configure
pytest_runtest_teardown = _guard.pytest_runtest_teardown
pytest_unconfigure = _guard.pytest_unconfigure
