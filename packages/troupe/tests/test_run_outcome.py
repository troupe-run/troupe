"""Tests for deriving a run's outcome (spec: actor-runners; design D4)."""

from pathlib import Path

import jsonschema
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from runner_schemas import SCHEMAS, load
from troupe.core.errors import TroupeError
from troupe.core.runners.effects import EffectVerdict, ExpectedFiles, NoEffectExpected
from troupe.core.runners.limits import RunLimits
from troupe.core.runners.outcome import (
    Ending,
    Outcome,
    RunFacts,
    RunOutcome,
    StopReason,
    derive_outcome,
)
from troupe.core.runners.protocol import ResultEvent

ERROR_SCHEMA = load(SCHEMAS / "error.schema.json")
RUN = "0f8fad5b-d9cb-469f-a165-70867728950e"
LIMITS = RunLimits()
OK = ResultEvent(RUN, 5, "ok", "done")
ERROR = ResultEvent(RUN, 5, "error", "API Error: 401")
PASSED = EffectVerdict(passed=True)
MISSING = EffectVerdict(
    passed=False, error=TroupeError("run.effect-missing", problem="p", fix="f", path="/w/out")
)
START_ERROR = TroupeError("runner.start-failed", problem="p", fix="f")
VIOLATION = TroupeError("runner.protocol", problem="p", fix="f")


def _facts(**overrides: object) -> RunFacts:
    values: dict[str, object] = {"limits": LIMITS, "ending": Ending.EXITED, "exit_code": 0}
    values.update(overrides)
    return RunFacts(**values)  # type: ignore[arg-type]


def _derive(**overrides: object) -> tuple[Outcome, str | None]:
    outcome, error = derive_outcome(_facts(**overrides))
    if error is not None:
        jsonschema.validate(error.to_data(), ERROR_SCHEMA)
    return outcome, None if error is None else error.code


# One test per row of design D4's table, in order


def test_a_runner_that_could_not_start_is_could_not_start() -> None:
    assert derive_outcome(_facts(start_error=START_ERROR, ending=Ending.NEVER_STARTED)) == (
        Outcome.COULD_NOT_START,
        START_ERROR,
    )


def test_a_protocol_violation_is_crashed_even_after_an_ok_result() -> None:
    assert _derive(violation=VIOLATION, result=OK, effect=PASSED) == (
        Outcome.CRASHED,
        "runner.protocol",
    )


def test_a_run_stopped_for_an_authentication_retry_is_failed() -> None:
    assert _derive(stop=StopReason.AUTHENTICATION) == (Outcome.FAILED, "run.authentication")


def test_a_run_stopped_at_its_transcript_limit_is_failed_naming_the_limit() -> None:
    outcome, error = derive_outcome(_facts(stop=StopReason.TRANSCRIPT_LIMIT))
    assert outcome is Outcome.FAILED
    assert error is not None
    assert error.code == "run.transcript-too-large"
    assert str(LIMITS.transcript_max_bytes) in error.problem


def test_an_error_result_with_exit_code_0_is_failed() -> None:
    assert _derive(result=ERROR, exit_code=0) == (Outcome.FAILED, "run.error-result")


def test_an_ok_result_whose_declared_output_is_missing_is_failed_naming_the_path() -> None:
    outcome, error = derive_outcome(_facts(result=OK, effect=MISSING))
    assert outcome is Outcome.FAILED
    assert error is MISSING.error


def test_an_ok_result_and_passing_effect_check_with_exit_code_3_is_failed_as_uncertain() -> None:
    outcome, error = derive_outcome(_facts(result=OK, effect=PASSED, exit_code=3))
    assert outcome is Outcome.FAILED
    assert error is not None
    assert error.code == "run.unclean-exit"
    assert "reported success but exited with code 3" in error.problem
    assert "uncertain" in error.problem


def test_an_ok_result_then_killed_during_shutdown_is_failed_as_uncertain() -> None:
    outcome, error = derive_outcome(
        _facts(result=OK, effect=PASSED, ending=Ending.KILLED, exit_code=-9)
    )
    assert outcome is Outcome.FAILED
    assert error is not None
    assert error.code == "run.unclean-exit"
    assert "killed" in error.problem


def test_an_ok_result_passing_effect_check_and_exit_code_0_is_succeeded() -> None:
    assert derive_outcome(_facts(result=OK, effect=PASSED, exit_code=0)) == (
        Outcome.SUCCEEDED,
        None,
    )


def test_no_result_after_the_run_timeout_is_timed_out_naming_the_limit() -> None:
    outcome, error = derive_outcome(_facts(stop=StopReason.RUN_TIMEOUT, exit_code=-9))
    assert outcome is Outcome.TIMED_OUT
    assert error is not None
    assert error.code == "run.timeout"
    assert f"{LIMITS.run_timeout:g}s" in error.problem


def test_a_cancelled_runner_that_sends_no_result_is_cancelled() -> None:
    assert _derive(stop=StopReason.CALLER, exit_code=143) == (Outcome.CANCELLED, None)


def test_a_runner_that_exits_mid_run_without_a_result_is_crashed() -> None:
    assert _derive(exit_code=1) == (Outcome.CRASHED, "runner.crashed")


def test_no_result_with_exit_code_0_is_crashed() -> None:
    assert _derive(exit_code=0) == (Outcome.CRASHED, "runner.crashed")


def test_a_result_wins_over_a_later_timeout_or_cancel() -> None:
    for stop in (StopReason.RUN_TIMEOUT, StopReason.CALLER):
        assert _derive(stop=stop, result=OK, effect=PASSED) == (Outcome.SUCCEEDED, None)


def test_an_ok_result_without_its_effect_verdict_is_a_bug_not_a_guess() -> None:
    with pytest.raises(ValueError, match="needs its effect verdict"):
        derive_outcome(_facts(result=OK))


# Every combination of facts


@settings(max_examples=500, deadline=None)
@given(
    ending=st.sampled_from(Ending),
    exit_code=st.none() | st.integers(-15, 255),
    start_error=st.none() | st.just(START_ERROR),
    violation=st.none() | st.just(VIOLATION),
    stop=st.none() | st.sampled_from(StopReason),
    result=st.none() | st.sampled_from([OK, ERROR]),
    effect=st.sampled_from([PASSED, MISSING]),
)
def test_every_combination_of_facts_yields_one_outcome_and_success_needs_all_three_signals(
    ending: Ending,
    exit_code: int | None,
    start_error: TroupeError | None,
    violation: TroupeError | None,
    stop: StopReason | None,
    result: ResultEvent | None,
    effect: EffectVerdict,
) -> None:
    facts = RunFacts(LIMITS, ending, exit_code, start_error, violation, stop, result, effect)
    outcome, error = derive_outcome(facts)
    assert outcome in Outcome
    assert (error is None) == (outcome in {Outcome.SUCCEEDED, Outcome.CANCELLED})
    if error is not None:
        jsonschema.validate(error.to_data(), ERROR_SCHEMA)
    if outcome is Outcome.SUCCEEDED:
        assert result is OK
        assert effect.passed
        assert exit_code == 0
        assert ending is Ending.EXITED
    if result is None:
        assert outcome is not Outcome.SUCCEEDED


def test_the_run_outcome_records_every_fact_as_data() -> None:
    record = RunOutcome(
        run_id=RUN,
        outcome=Outcome.FAILED,
        error=VIOLATION,
        result=OK,
        exit_code=3,
        ending=Ending.EXITED,
        transcript="sha256:" + "0" * 64,
        stderr="sha256:" + "1" * 64,
        limits=LIMITS,
    ).to_data()
    assert record["outcome"] == "failed"
    assert record["exitCode"] == 3
    assert record["result"] == OK.to_data()
    assert record["limits"] == LIMITS.to_data()


# Effect checks (design D10)


def test_no_effect_expected_always_passes() -> None:
    check = NoEffectExpected()
    check.before()
    assert check.after() == PASSED


def test_expected_files_pass_when_each_is_new_or_changed(tmp_path: Path) -> None:
    changed = tmp_path / "changed.txt"
    changed.write_text("before", encoding="utf-8")
    new = tmp_path / "new.txt"
    check = ExpectedFiles([changed, new])
    check.before()
    changed.write_text("after", encoding="utf-8")
    new.write_text("hi", encoding="utf-8")
    assert check.after().passed


def test_expected_files_fail_naming_a_missing_file(tmp_path: Path) -> None:
    check = ExpectedFiles([tmp_path / "out" / "hello.txt"])
    check.before()
    verdict = check.after()
    assert not verdict.passed
    assert verdict.error is not None
    assert verdict.error.code == "run.effect-missing"
    assert verdict.error.path == str(tmp_path / "out" / "hello.txt")


def test_expected_files_fail_for_an_existing_file_left_unchanged(tmp_path: Path) -> None:
    same = tmp_path / "same.txt"
    same.write_text("unchanged", encoding="utf-8")
    check = ExpectedFiles([same])
    check.before()
    verdict = check.after()
    assert not verdict.passed
    assert verdict.error is not None
    assert "unchanged" in verdict.error.problem


def test_expected_files_needs_at_least_one_path() -> None:
    with pytest.raises(ValueError, match="NoEffectExpected"):
        ExpectedFiles([])
