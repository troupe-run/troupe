"""The project's hypothesis profiles (hypothesis_profiles.py, loaded for every test path).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_hypothesis_profiles.py."""

from pathlib import Path

import pytest
from hypothesis import settings
from hypothesis.database import DirectoryBasedExampleDatabase

from hypothesis_profiles import shared_database


def test_no_profile_a_run_can_use_has_a_per_example_deadline() -> None:
    assert settings.get_profile("default").deadline is None
    assert settings.get_profile("ci").deadline is None
    assert settings().deadline is None  # whichever is active


def test_ci_still_uses_fixed_seeds_and_no_database() -> None:
    ci = settings.get_profile("ci")
    assert ci.derandomize is True
    assert ci.database is None


def test_every_run_shares_the_roots_example_database(pytestconfig: pytest.Config) -> None:
    # #537: a failure found from packages/troupe was never replayed by the check from the root.
    # The root is where the configuration this run uses really is: the nightly mutation run links
    # the root's pyproject.toml into packages/ beside mutmut's copy, and pytest reads it there
    # (#543).
    assert pytestconfig.inipath is not None, "the run found no pytest configuration"
    root = pytestconfig.inipath.resolve().parent
    database = shared_database({})
    assert isinstance(database, DirectoryBasedExampleDatabase)
    assert Path(database.path) == root / ".hypothesis" / "examples"


def test_a_storage_directory_from_the_environment_leaves_hypothesiss_own_database() -> None:
    assert shared_database({"HYPOTHESIS_STORAGE_DIRECTORY": "elsewhere"}) is None
    assert isinstance(
        shared_database({"HYPOTHESIS_STORAGE_DIRECTORY": ""}), DirectoryBasedExampleDatabase
    )
