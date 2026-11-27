"""troupe perform on the command line, run in-process against a stand-in core: the request it
sends, the updates it shows while the run goes, what it prints at the end and its exit code, and
what Ctrl-C does (spec: cli; perform-status-logs design D10, D14; worktree-stage design D6;
unit-tests-cli-commands-config-init design D1-D3).

Each result and update is the protocol's own message, in the shapes the core returned for a
scripted actor's run in a git theatre (its startedBy made anonymous). The lines the CLI takes from
troupe.cli.render are built with it here; that module's tests pin their text. Its tests that start
a process, open a socket or use a git theatre are in integration/."""

import copy
import os
from pathlib import Path
from typing import Any

import pytest

from cli_core_stand_in import StandIn, stand_in
from troupe.cli.render import render_event
from troupe.core.client.messages import LoggedEvent, NoticeUpdate, PerformResult, Started
from troupe.core.exit_codes import ExitCode

RUN_ID = "57468ead-167b-4c35-887e-1af08e16144c"
SHORT = "57468ead"
BASE = "06e610bf0077235089a2da29b9fbc7fafd000c2a"
WORKTREE = f".troupe/local/worktrees/{RUN_ID}"
EMPTY = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
DIFF = "sha256:2f743dfc4438f26e732e5e3af0a9c8b6d90289a70ea6983bd659db36e6bfef35"
STAGE = {
    "name": "local",
    "effects": "unenforced",
    "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
}
PENDING = {
    "state": "pending",
    "diff": DIFF,
    "added": 1,
    "modified": 0,
    "deleted": 0,
    "leftOut": 0,
    "worktree": WORKTREE,
}
RUN: dict[str, Any] = {
    "runId": RUN_ID,
    "actor": "lead",
    "startedBy": {"kind": "human", "id": "ada@example.com", "source": "vcs"},
    "runner": {"requested": "scripted", "reported": {"name": "scripted", "version": "0.2.0"}},
    "stage": STAGE,
    "effectCheck": {"kind": "files", "paths": ["AUDITION.md"]},
    "workspace": {
        "kind": "worktree",
        "path": WORKTREE,
        "base": BASE,
        "dirty": False,
        "clones": ["clonefile"],
    },
    "state": "ended",
    "outcome": "succeeded",
    "audit": {"outside": []},
    "events": 2,
    "startedAt": "2026-11-26T06:56:23.444Z",
    "endedAt": "2026-11-26T06:56:24.216Z",
    "transcript": EMPTY,
    "transcriptFormat": "native",
    "stderr": EMPTY,
    "changes": PENDING,
    "approvers": {"value": ["troupe", "director"], "source": "default"},
}
EVENTS: list[dict[str, Any]] = [
    {
        "kind": "event",
        "runId": RUN_ID,
        "seq": 0,
        "at": "2026-11-26T06:56:23.949Z",
        "event": {
            "type": "init",
            "runId": RUN_ID,
            "seq": 0,
            "runner": {"name": "scripted", "version": "0.2.0"},
            "tools": ["Write"],
            "effects": "checked",
        },
    },
    {
        "kind": "event",
        "runId": RUN_ID,
        "seq": 1,
        "at": "2026-11-26T06:56:23.951Z",
        "event": {
            "type": "result",
            "runId": RUN_ID,
            "seq": 1,
            "status": "ok",
            "message": "wrote AUDITION.md",
        },
    },
]
UNSEEN = {
    "code": "workspace.uncommitted-unseen",
    "problem": "1 path(s) differ from HEAD (06e610bf0077), and the run won't see them: it works "
    "in its own worktree, made from HEAD. Accepting its changes may conflict with yours.",
    "fix": "Commit or stash your changes first if the run needs them. Otherwise, nothing to do.",
    "details": {"count": 1, "paths": ["AUDITION.md"], "base": BASE},
}
REHEARSAL: dict[str, Any] = {
    "actor": "lead",
    "runner": "scripted",
    "stage": STAGE,
    "effectCheck": {"kind": "files", "paths": ["AUDITION.md", "NOTES.md"]},
    "effects": {"write": ["AUDITION.md"], "delete": ["old/**"], "move": []},
    "config": [
        "sha256:c09e93145426ec0623c07e0ac8105d659ed857780d145469161d82e501eb7f7d",
        "sha256:" + "1" * 64,
    ],
    "direction": {
        "hash": "sha256:4cd0e21a9a0795a14ec9aa5f0e7d1abff0492565770e43eafdf1e3e8afed1f33",
        "length": 2,
    },
    "workspace": {"kind": "worktree", "base": BASE},
}
WOULD = [
    "would perform lead",
    "  runner: scripted",
    "  stage: local, effects unenforced",
    "  effect check: AUDITION.md, NOTES.md",
    "  effects: write AUDITION.md; delete old/**",
    "  character: none",
    "  direction: 2 characters, "
    "sha256:4cd0e21a9a0795a14ec9aa5f0e7d1abff0492565770e43eafdf1e3e8afed1f33",
    "  config: sha256:c09e93145426ec0623c07e0ac8105d659ed857780d145469161d82e501eb7f7d, "
    f"sha256:{'1' * 64}",
    f"  workspace: its own worktree, made at {BASE}",
    "Rehearsal: nothing was started or recorded.",
]
STARTING = (
    f"troupe: run {RUN_ID} starting; follow it from another terminal with "
    f"`troupe logs {SHORT} --follow`"
)
IN_WORKTREE = (
    f"troupe: run {SHORT} works in its own worktree, {WORKTREE}; your files change only when "
    "its work is kept at its gate."
)


def _in_theatre(**fields: Any) -> PerformResult:  # noqa: ANN401
    return _run(workspace={"kind": "theatre"}, changes=None, approvers=None, **fields)


def _run(**fields: Any) -> PerformResult:  # noqa: ANN401
    run = {**copy.deepcopy(RUN), **fields}
    for name in [name for name, value in fields.items() if value is None]:
        del run[name]
    return PerformResult.from_data({"run": run})


def _started(*, worktree: bool = True) -> Started:
    data = {"kind": "started", "runId": RUN_ID}
    return Started.from_data({**data, "worktree": WORKTREE} if worktree else data)


def _events() -> list[LoggedEvent]:
    return [LoggedEvent.from_data(event) for event in EVENTS]


@pytest.fixture
def core(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> StandIn:
    return stand_in(monkeypatch, tmp_path)


def test_perform_sends_the_actor_and_direction(core: StandIn) -> None:
    core.reply("perform", _run())
    core.run("perform", "lead", "--direction", "go")
    assert core.requests == [("perform", {"actor": "lead", "direction": "go"})]


def test_perform_without_a_direction_sends_none(core: StandIn) -> None:
    core.reply("perform", _run())
    core.run("perform", "lead")
    assert core.requests == [("perform", {"actor": "lead"})]


def test_a_succeeded_worktree_run_shows_its_updates_then_how_to_settle_it(core: StandIn) -> None:
    core.reply("perform", _run(), _started(), *_events())
    ran = core.run("perform", "lead", "--direction", "go")
    assert ran.code == ExitCode.OK
    assert ran.out == [f"run {RUN_ID} succeeded"]
    assert ran.err == [
        STARTING,
        IN_WORKTREE,
        render_event(EVENTS[0]),
        render_event(EVENTS[1]),
        f"troupe: run {SHORT}'s changes are in its worktree, {WORKTREE}, not yet in your files. "
        f"See them with `troupe diff {SHORT}`, then `troupe accept {SHORT}` or "
        f"`troupe discard {SHORT}`.",
    ]


def test_a_run_in_the_theatre_names_no_worktree_and_no_next_step(core: StandIn) -> None:
    core.reply("perform", _in_theatre(), _started(worktree=False))
    ran = core.run("perform", "lead")
    assert ran.err == [STARTING]
    assert ran.out == [f"run {RUN_ID} succeeded"]


def test_a_notice_sent_while_the_run_goes_is_shown_on_standard_error(core: StandIn) -> None:
    notice = NoticeUpdate.from_data({"kind": "notice", "notice": UNSEEN})
    core.reply("perform", _run(), notice, _started())
    ran = core.run("perform", "lead")
    assert ran.err[:3] == [f"troupe: {UNSEEN['problem']}", f"  fix: {UNSEEN['fix']}", STARTING]


def test_a_run_that_changed_nothing_says_discarding_removes_its_worktree(core: StandIn) -> None:
    changes = {"state": "none", "worktree": WORKTREE}
    core.reply("perform", _run(changes=changes))
    ran = core.run("perform", "lead")
    assert ran.err == [
        f"troupe: run {SHORT} changed nothing. `troupe discard {SHORT}` removes its worktree, "
        f"{WORKTREE}."
    ]


def test_a_run_whose_changes_werent_captured_says_where_to_look(core: StandIn) -> None:
    changes = {"state": "uncaptured", "worktree": WORKTREE}
    core.reply("perform", _run(changes=changes))
    ran = core.run("perform", "lead")
    assert ran.err == [
        f"troupe: run {SHORT}'s changes weren't captured. Look at what it wrote in {WORKTREE}, "
        f"then `troupe discard {SHORT}`."
    ]


def test_a_cancelled_run_says_so_and_exits_cancelled(core: StandIn) -> None:
    core.reply("perform", _in_theatre(outcome="cancelled"))
    ran = core.run("perform", "lead")
    assert ran.code == ExitCode.CANCELLED
    assert ran.out == []
    assert ran.err == [f"troupe: run {RUN_ID} was cancelled."]


@pytest.mark.parametrize(
    ("outcome", "error"),
    [
        ("failed", {"code": "run.authentication", "problem": "It stopped.", "fix": "Log in."}),
        (
            "timed-out",
            {
                "code": "run.timeout",
                "problem": "It stopped.",
                "fix": "Log in.",
                "details": {"limitSeconds": 600},
            },
        ),
    ],
)
def test_a_run_that_didnt_succeed_shows_its_error_and_outcome_and_fails(
    core: StandIn, outcome: str, error: dict[str, Any]
) -> None:
    core.reply("perform", _in_theatre(outcome=outcome, error=error))
    ran = core.run("perform", "lead")
    assert ran.code == ExitCode.FAILURE
    assert ran.out == []
    assert ran.err == [
        "troupe: It stopped.",
        "  fix: Log in.",
        f"  run: {RUN_ID} ({outcome})",
    ]


def test_a_rehearsal_says_what_would_run_and_would_change(core: StandIn) -> None:
    core.reply("perform", PerformResult.from_data({"rehearsal": REHEARSAL}))
    ran = core.run("perform", "lead", "--direction", "go", "--rehearse")
    assert core.requests == [("perform", {"actor": "lead", "direction": "go", "rehearse": True})]
    assert ran.code == ExitCode.WOULD_CHANGE
    assert ran.out == WOULD
    assert ran.stderr == ""


def test_a_rehearsal_in_the_theatre_with_no_check_or_effects_and_a_runtime(
    core: StandIn,
) -> None:
    rehearsal = {
        **REHEARSAL,
        "effectCheck": {"kind": "none"},
        "effects": {"write": [], "delete": [], "move": []},
        "character": {"hash": EMPTY, "length": 120},
        "workspace": {"kind": "theatre"},
        "runtime": {"name": "ollama", "endpoint": {"value": "http://x", "source": "default"}},
    }
    del rehearsal["direction"]
    core.reply("perform", PerformResult.from_data({"rehearsal": rehearsal}))
    ran = core.run("perform", "lead", "--rehearse")
    assert ran.out[3:9] == [
        "  effect check: no effect check",
        "  effects: none declared, so the actor is read-only",
        f"  character: 120 characters, {EMPTY}",
        "  direction: none",
        WOULD[7],
        "  workspace: the theatre",
    ]
    assert ran.out[9].startswith("  runtime ollama")
    assert ran.out[-1] == "Rehearsal: nothing was started or recorded."


def test_effects_are_listed_write_delete_then_move() -> None:
    from troupe.cli.commands import _effects

    effects = {"move": ["c"], "delete": ["b", "d"], "write": ["a"]}
    assert _effects(effects) == "write a; delete b, d; move c"


def test_ctrl_c_asks_the_run_to_cancel_and_says_how_it_will_stop(core: StandIn) -> None:
    core.reply("perform", _in_theatre(outcome="cancelled"), _started(), presses=1)
    ran = core.run("perform", "lead")
    assert ran.logged == ()  # no error from the Ctrl-C handler
    assert core.calls[0].session.cancel.requested
    assert ran.err == [
        STARTING,
        IN_WORKTREE,
        "troupe: Cancelling the run: the runner has been asked to stop, and will be stopped if it "
        "doesn't within its grace period.",
        "  fix: Wait: troupe records how the run ended before it exits, so the run isn't left "
        "unrecorded.",
        f"troupe: run {RUN_ID} was cancelled.",
    ]
    assert ran.code == ExitCode.CANCELLED


def test_a_second_ctrl_c_says_troupe_is_already_cancelling(core: StandIn) -> None:
    core.reply("perform", _in_theatre(outcome="cancelled"), presses=2)
    ran = core.run("perform", "lead")
    assert ran.logged == ()  # no error from the Ctrl-C handler
    assert ran.err[2] == (
        "troupe: Cancelling the run: the runner has been asked to stop, and will be stopped if it "
        "doesn't within its grace period. troupe is already cancelling it."
    )
    assert ran.err[0] == ran.err[2].removesuffix(" troupe is already cancelling it.")


def test_the_run_starts_in_a_session_for_the_theatre_found_from_here(
    core: StandIn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    below = tmp_path / "src" / "deep"
    below.mkdir(parents=True)
    monkeypatch.chdir(below)
    core.reply("perform", _run())
    core.run("perform", "lead")
    (call,) = core.calls
    assert call.session.theatre == tmp_path.resolve()
    assert dict(call.session.env) == dict(os.environ)
    assert not call.session.cancel.requested


# Requirement: Perform says where a worktree run works (spec: cli; manual-gates)
# Requirement: Perform's exit code follows the run's outcome

AT = "2026-11-26T06:56:25.000Z"
TROUPE = {"kind": "system", "id": "core@build-01"}


def test_a_run_kept_at_its_gate_names_the_files_and_who_approved_and_exits_0(
    core: StandIn,
) -> None:
    kept = {
        **{k: v for k, v in PENDING.items() if k != "worktree"},
        "state": "accepted",
        "settledAt": AT,
        "files": ["AUDITION.md"],
    }
    gate = [{"step": "approved", "role": "troupe", "actor": TROUPE, "at": AT}]
    core.reply("perform", _run(changes=kept, gate=gate), _started())
    ran = core.run("perform", "lead")
    assert ran.code == ExitCode.OK
    assert ran.out == [f"run {RUN_ID} succeeded"]
    assert ran.err[-1] == (
        f"troupe: run {SHORT}'s changes were kept, approved by troupe, unstaged: AUDITION.md."
    )


def test_a_run_waiting_after_a_conflict_says_it_succeeded_names_the_role_files_answers_exit_4(
    core: StandIn,
) -> None:
    waiting = {**PENDING, "state": "waiting", "cue": {"role": "director", "raisedAt": AT}}
    gate = [
        {
            "step": "passed",
            "approver": "troupe",
            "to": "director",
            "files": ["src/a.txt"],
            "at": AT,
        },
        {"step": "cue", "role": "director", "at": AT},
    ]
    core.reply("perform", _run(changes=waiting, gate=gate), _started())
    ran = core.run("perform", "lead")
    assert ran.code == ExitCode.WAITING
    assert int(ran.code) == 4
    assert ran.out == [f"run {RUN_ID} succeeded"]
    assert ran.err[-1] == (
        f"troupe: run {SHORT} succeeded, and its work waits at its gate for director because "
        "src/a.txt conflicts with your files: exit 4 means waiting for director, not failure. "
        f"Its changes are in its worktree, {WORKTREE}. See them with `troupe diff {SHORT}`, then "
        f"`troupe approve {SHORT}` or `troupe reject {SHORT}`."
    )


def test_a_run_waiting_for_a_person_says_it_succeeded_and_exit_4_is_waiting_not_failure(
    core: StandIn,
) -> None:
    waiting = {**PENDING, "state": "waiting", "cue": {"role": "director", "raisedAt": AT}}
    gate = [{"step": "cue", "role": "director", "at": AT}]
    core.reply("perform", _run(changes=waiting, gate=gate), _started())
    ran = core.run("perform", "lead")
    assert ran.code == ExitCode.WAITING
    assert ran.err[-1] == (
        f"troupe: run {SHORT} succeeded, and its work waits at its gate for director: exit 4 "
        f"means waiting for director, not failure. Its changes are in its worktree, {WORKTREE}. "
        f"See them with `troupe diff {SHORT}`, then `troupe approve {SHORT}` or "
        f"`troupe reject {SHORT}`."
    )


def test_a_rehearsal_shows_the_approvers_it_would_use(core: StandIn) -> None:
    rehearsal = {
        **REHEARSAL,
        "approvers": {"value": ["troupe", "director"], "source": "default"},
    }
    core.reply("perform", PerformResult.from_data({"rehearsal": rehearsal}))
    ran = core.run("perform", "lead", "--rehearse")
    assert "  approvers: troupe, director (default)" in ran.out
