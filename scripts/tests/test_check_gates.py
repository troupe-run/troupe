"""check.py runs the complexity gate everywhere, and coverage and the audit on CI's coverage leg
only (spec: quality-check; quality-gates design D3)."""

import pytest

import check


def labels(steps: list[tuple[str, list[str]]]) -> list[str]:
    return [label for label, _ in steps]


def test_a_local_check_runs_complexity_but_never_coverage_or_audit() -> None:
    steps = check.gates()
    assert "complexity" in labels(steps)
    assert "coverage" not in labels(steps)
    assert "audit" not in labels(steps)
    assert not any(arg.startswith("--cov") for arg in dict(steps)["tests"])


def test_complexity_runs_before_the_tests_and_takes_the_base() -> None:
    steps = check.gates(base="abc123")
    assert labels(steps).index("complexity") < labels(steps).index("tests")
    assert dict(steps)["complexity"][-3:] == ["complexity", "--base", "abc123"]


def test_the_leg_measures_coverage_from_the_full_test_run_and_audits() -> None:
    steps = check.gates(base="abc123", leg=True)
    report = str(check.coverage_report())
    assert f"--cov-report=json:{report}" in dict(steps)["tests"]
    assert dict(steps)["coverage"][-3:] == ["coverage", "--coveragepy", report]
    assert dict(steps)["audit"][-3:] == ["audit", "--base", "abc123"]
    assert labels(steps).index("tests") < labels(steps).index("coverage")


def test_a_scoped_check_on_the_leg_says_coverage_wasnt_measured() -> None:
    steps = check.gates(("docs",), leg=True)
    assert not any(arg.startswith("--cov") for arg in dict(steps)["tests"])
    assert "coverage not measured: the tests were scoped" in dict(steps)["coverage"][-1]
    assert "audit" in labels(steps)


def test_the_leg_is_off_unless_its_variable_is_set() -> None:
    assert check.on_leg({}) is False
    assert check.on_leg({"GITHUB_ACTIONS": "true"}) is False
    assert check.on_leg({check.LEG: "true", "GITHUB_ACTIONS": "true"}) is True


def test_the_leg_variable_outside_github_actions_stops_the_check() -> None:
    with pytest.raises(SystemExit) as refused:
        check.on_leg({check.LEG: "true"})
    assert "isn't GitHub Actions" in str(refused.value.code)
    assert f"unset {check.LEG}" in str(refused.value.code)


def test_a_malformed_leg_value_stops_the_check() -> None:
    with pytest.raises(SystemExit) as refused:
        check.on_leg({check.LEG: "yes", "GITHUB_ACTIONS": "true"})
    assert "QUALITY_GATES_LEG='yes' isn't valid" in str(refused.value.code)
