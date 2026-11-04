"""A test of the plugin's fails when it leaves a stand-in claude running (reap-fake-claude
design D3). Only re-exports, so it's left out of mypy (pyproject.toml)."""

from stand_in_guard import pytest_configure, pytest_runtest_teardown, pytest_unconfigure

__all__ = ["pytest_configure", "pytest_runtest_teardown", "pytest_unconfigure"]
