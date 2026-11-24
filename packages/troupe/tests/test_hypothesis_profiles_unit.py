"""The project's hypothesis profiles (hypothesis_profiles.py, loaded for every test path).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_hypothesis_profiles.py."""

from hypothesis import settings


def test_no_profile_a_run_can_use_has_a_per_example_deadline() -> None:
    assert settings.get_profile("default").deadline is None
    assert settings.get_profile("ci").deadline is None
    assert settings().deadline is None  # whichever is active


def test_ci_still_uses_fixed_seeds_and_no_database() -> None:
    ci = settings.get_profile("ci")
    assert ci.derandomize is True
    assert ci.database is None
