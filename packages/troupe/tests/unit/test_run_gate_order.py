"""The order of a run's gate events: a pass, a cue, then one settling event (spec: gates;
manual-gates design D4). The aggregate is the backstop behind the commands' own checks."""

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest

from runtesting import STAGE, outcome
from troupe.core.errors import TroupeError
from troupe.core.runs.aggregate import Run

WORKTREE = {
    "kind": "worktree",
    "path": ".troupe/local/worktrees/run",
    "base": "c" * 40,
    "dirty": False,
}
DIFF = "sha256:" + "d" * 64
BRIEF = {
    "actor": "tester",
    "outcome": "succeeded",
    "diff": DIFF,
    "added": 1,
    "modified": 0,
    "deleted": 0,
}


def ended() -> Run:
    run = Run(
        run_id=str(uuid4()),
        actor="tester",
        runner_requested="scripted",
        stage=STAGE,
        effect_check={"kind": "none"},
        direction="sha256:" + "a" * 64,
        config=["sha256:" + "b" * 64],
        workspace=WORKTREE,
        on_context_full={"value": "fail", "source": "default"},
        step=1,
        approvers={"value": ["troupe", "director"], "source": "default"},
    )
    run.end(outcome("succeeded"), None, {"diff": DIFF, "added": 1, "modified": 0, "deleted": 0})
    run.collect_events()
    return run


def passed(run: Run) -> Run:
    run.pass_gate("troupe", "director", ["src/a.txt"])
    return run


def cued(run: Run) -> Run:
    run.raise_cue("director", BRIEF)
    return run


def names(run: Run) -> list[str]:
    return [type(event).__qualname__ for event in run.collect_events()]


def test_troupe_keeping_the_changes_settles_them_with_no_pass_or_cue() -> None:
    run = ended()
    run.accept_changes(DIFF, ["src/a.txt"], approved_as="troupe")
    assert names(run) == ["Run.ChangesAccepted"]
    assert run.settled == "accepted"


def test_a_pass_then_a_cue_then_an_approval_in_the_cues_role_is_the_order_of_a_conflict() -> None:
    run = cued(passed(ended()))
    run.accept_changes(DIFF, ["src/a.txt"], approved_as="director")
    assert names(run) == ["Run.GatePassed", "Run.CueRaised", "Run.ChangesAccepted"]


def test_a_cue_then_a_rejection_settles_the_changes_as_rejected() -> None:
    run = cued(ended())
    run.reject_changes("director")
    assert names(run) == ["Run.CueRaised", "Run.ChangesRejected"]
    assert run.settled == "rejected"


@pytest.mark.parametrize(
    ("settle", "discarding"),
    [
        (lambda run: run.accept_changes(DIFF, ["src/a.txt"]), False),
        (lambda run: run.accept_changes(DIFF, ["src/a.txt"], approved_as="troupe"), False),
        (lambda run: run.discard_changes(), True),
    ],
    ids=["an accept", "troupe's approval", "a discard"],
)
def test_while_a_cue_is_open_anything_but_its_roles_answer_is_refused_as_waiting_at_gate(
    settle: Callable[[Run], None], discarding: bool
) -> None:
    run = cued(ended())
    run.collect_events()
    with pytest.raises(TroupeError) as caught:
        settle(run)
    assert caught.value.code == "run.waiting-at-gate"
    assert caught.value.details["role"] == "director"
    assert caught.value.details["command"].startswith(
        "troupe reject" if discarding else "troupe approve"
    )
    assert run.collect_events() == []


def test_a_rejection_with_no_open_cue_is_refused_as_no_cue() -> None:
    run = ended()
    with pytest.raises(TroupeError) as caught:
        run.reject_changes("director")
    assert caught.value.code == "gate.no-cue"


def test_a_rejected_run_can_be_settled_no_more() -> None:
    run = cued(ended())
    run.reject_changes("director")
    with pytest.raises(TroupeError) as caught:
        run.accept_changes(DIFF, ["src/a.txt"], approved_as="director")
    assert caught.value.code == "run.changes-settled"
    assert caught.value.details["settled"] == "rejected"


def before_end() -> Run:
    run = ended()
    fresh = Run(
        run_id=str(uuid4()),
        actor=run.actor,
        runner_requested=run.runner_requested,
        stage=run.stage,
        effect_check=run.effect_check,
        direction=run.direction,
        config=run.config,
        workspace=WORKTREE,
        on_context_full=run.on_context_full,
        step=1,
        approvers=run.approvers,
    )
    fresh.collect_events()
    return fresh


def settled(run: Run) -> Run:
    run.accept_changes(DIFF, ["src/a.txt"], approved_as="troupe")
    return run


@pytest.mark.parametrize(
    ("make", "step"),
    [
        (before_end, passed),
        (before_end, cued),
        (lambda: settled(ended()), passed),
        (lambda: settled(ended()), cued),
        (lambda: passed(ended()), passed),
        (lambda: cued(ended()), passed),
        (lambda: cued(ended()), cued),
    ],
    ids=[
        "a pass before the end",
        "a cue before the end",
        "a pass after settling",
        "a cue after settling",
        "a second pass",
        "a pass after the cue",
        "a second cue",
    ],
)
def test_a_gate_event_out_of_its_order_is_refused_as_out_of_sequence(
    make: Callable[[], Run], step: Callable[[Run], Run]
) -> None:
    run = make()
    run.collect_events()
    with pytest.raises(TroupeError) as caught:
        step(run)
    assert caught.value.code == "run.out-of-sequence"
    assert run.collect_events() == []


def test_only_troupe_passes() -> None:
    run = ended()
    with pytest.raises(TroupeError) as caught:
        run.pass_gate("director", "troupe", ["src/a.txt"])
    assert caught.value.code == "run.out-of-sequence"


def test_brief_is_kept_as_given(  # the payload is recorded as built
) -> None:
    run = ended()
    run.raise_cue("director", BRIEF)
    [event] = run.collect_events()
    state: dict[str, Any] = vars(event)
    assert state["role"] == "director"
    assert state["brief"] == BRIEF
