"""The project's hypothesis profiles (hypothesis_profiles.py, loaded for every test path).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_hypothesis_profiles.py."""

from pathlib import Path

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


def repository_root() -> Path:
    """The directory holding the root pyproject.toml, the one with pytest's configuration."""
    return next(
        p
        for p in Path(__file__).resolve().parents
        if (p / "pyproject.toml").is_file()
        and "[tool.pytest.ini_options]" in (p / "pyproject.toml").read_text("utf-8")
    )


def test_every_run_shares_the_roots_example_database() -> None:
    # #537: a failure found from packages/troupe was never replayed by the check from the root.
    database = shared_database({})
    assert isinstance(database, DirectoryBasedExampleDatabase)
    assert Path(database.path) == repository_root() / ".hypothesis" / "examples"


def test_a_storage_directory_from_the_environment_leaves_hypothesiss_own_database() -> None:
    assert shared_database({"HYPOTHESIS_STORAGE_DIRECTORY": "elsewhere"}) is None
    assert isinstance(
        shared_database({"HYPOTHESIS_STORAGE_DIRECTORY": ""}), DirectoryBasedExampleDatabase
    )
