"""Tests for deriving a run's outcome (spec: actor-runners; design D4)."""

from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from protocol_schemas import check_error
from troupe.core.errors import TroupeError
from troupe.core.runners.effects import (
    AuditFindings,
    Change,
    EffectVerdict,
    ExpectedFiles,
    NoEffectExpected,
    audit_failed,
)
from troupe.core.runners.limits import RunLimits
from troupe.core.runners.outcome import (
    FAILURES,
    Ending,
    Outcome,
    RunFacts,
    RunOutcome,
    StopReason,
    derive_outcome,
)
from troupe_plugin_sdk.runner import FAILURE_REASONS, FailureReason, ResultEvent

RUN = "0f8fad5b-d9cb-469f-a165-70867728950e"
LIMITS = RunLimits()
OK = ResultEvent(RUN, 5, "ok", "done")
ERROR = ResultEvent(RUN, 5, "error", "API Error: 401", reason="authentication")
PASSED = EffectVerdict(passed=True)
MISSING = EffectVerdict(
    passed=False, error=TroupeError("run.effect-missing", problem="p", fix="f", path="/w/out")
)
OUTSIDE = EffectVerdict(
    passed=False,
    error=TroupeError(
        "effects.outside-declared",
        problem="p",
        fix="f",
        details={
            "actor": "tester",
            "changes": [{"path": "src/a.py", "change": "added", "needs": "write"}],
        },
    ),
)
UNREADABLE = EffectVerdict(
    passed=False, error=audit_failed(TroupeError("internal.unexpected", problem="p", fix="f"))
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
        check_error(error.to_data())
    return outcome, None if error is None else error.code


# One test per row of design D4's table, in order


def test_a_runner_that_could_not_start_is_could_not_start() -> None:
    assert derive_outcome(
        _facts(start_error=START_ERROR, ending=Ending.NEVER_STARTED, exit_code=None)
    ) == (
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


# Requirement: A failed result's reason reaches the outcome


def _failed(reason: FailureReason, message: str = "the runner's words") -> TroupeError:
    result = ResultEvent(RUN, 5, "error", message, reason=reason)
    outcome, error = derive_outcome(_facts(result=result))
    assert outcome is Outcome.FAILED
    assert error is not None
    return error


def test_a_refused_credential_carries_its_reason_and_says_to_check_the_credential() -> None:
    error = _failed("authentication", "Incorrect API key provided")
    assert error.code == "run.error-result"
    assert error.details == {"reason": "authentication", "message": "Incorrect API key provided"}
    assert "refused the credential" in error.problem
    assert "Incorrect API key provided" in error.problem
    assert "credential the actor's runtime names" in error.fix


def test_a_spent_budget_says_to_raise_the_budget_or_give_a_smaller_task() -> None:
    error = _failed("budget")
    assert error.details is not None
    assert error.details["reason"] == "budget"
    assert "Raise the budget in the actor's runner options" in error.fix
    assert "smaller task" in error.fix


@pytest.mark.parametrize("reason", FAILURE_REASONS)
def test_every_reason_gives_a_valid_error_with_a_fix_written_for_it(reason: FailureReason) -> None:
    error = _failed(reason)
    check_error(error.to_data())
    generic = FAILURES["other"][1]
    assert reason == "other" or error.fix != generic


def test_every_reason_on_the_list_has_an_entry_in_the_table() -> None:
    assert sorted(FAILURES) == sorted(FAILURE_REASONS)


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
    exit_code=st.integers(-15, 255),
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
    # A runner that never started has no exit code; one that started always has one.
    code = None if ending is Ending.NEVER_STARTED else exit_code
    facts = RunFacts(LIMITS, ending, code, start_error, violation, stop, result, effect)
    outcome, error = derive_outcome(facts)
    assert outcome in Outcome
    assert (error is None) == (outcome in {Outcome.SUCCEEDED, Outcome.CANCELLED})
    if error is not None:
        check_error(error.to_data())
    if outcome is Outcome.SUCCEEDED:
        assert result is OK
        assert effect.passed
        assert code == 0
        assert ending is Ending.EXITED
    if result is None:
        assert outcome is not Outcome.SUCCEEDED


@settings(max_examples=500, deadline=None)
@given(
    ending=st.sampled_from(Ending),
    exit_code=st.integers(-15, 255),
    start_error=st.none() | st.just(START_ERROR),
    violation=st.none() | st.just(VIOLATION),
    stop=st.none() | st.sampled_from(StopReason),
    result=st.none() | st.just(ERROR),
    effect=st.sampled_from([PASSED, MISSING, OUTSIDE, UNREADABLE]),
)
def test_without_an_ok_result_no_effect_or_audit_verdict_changes_the_outcome_or_its_error(
    ending: Ending,
    exit_code: int,
    start_error: TroupeError | None,
    violation: TroupeError | None,
    stop: StopReason | None,
    result: ResultEvent | None,
    effect: EffectVerdict,
) -> None:
    # A failed run's audit is recorded beside its outcome, never in it (failed-run-audit D1).
    code = None if ending is Ending.NEVER_STARTED else exit_code
    without = RunFacts(LIMITS, ending, code, start_error, violation, stop, result, None)
    with_verdict = RunFacts(LIMITS, ending, code, start_error, violation, stop, result, effect)
    assert _as_data(derive_outcome(with_verdict)) == _as_data(derive_outcome(without))


def _as_data(
    derived: tuple[Outcome, TroupeError | None],
) -> tuple[Outcome, dict[str, object] | None]:
    outcome, error = derived
    return outcome, None if error is None else error.to_data()


@pytest.mark.parametrize(
    ("ending", "exit_code"),
    [(Ending.NEVER_STARTED, 0), (Ending.EXITED, None), (Ending.KILLED, None)],
)
def test_an_exit_code_that_disagrees_with_how_the_runner_ended_is_refused(
    ending: Ending, exit_code: int | None
) -> None:
    with pytest.raises(ValueError, match="exit code exactly when it started"):
        RunFacts(LIMITS, ending, exit_code)


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
    assert "audit" not in record


def test_the_run_outcome_records_its_audit_after_the_runners_standard_error() -> None:
    findings = AuditFindings(outside=(Change("src/a.py", "added", "write"),))
    record = RunOutcome(
        run_id=RUN,
        outcome=Outcome.CANCELLED,
        error=None,
        result=None,
        exit_code=0,
        ending=Ending.EXITED,
        transcript="sha256:" + "0" * 64,
        stderr="sha256:" + "1" * 64,
        limits=LIMITS,
        audit=findings,
    ).to_data()
    assert record["audit"] == {
        "outside": [{"path": "src/a.py", "change": "added", "needs": "write"}]
    }
    assert list(record)[-1] == "audit"


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
