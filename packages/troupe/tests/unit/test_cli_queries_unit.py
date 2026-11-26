"""troupe status, logs, diff, accept and discard on the command line, run in-process against a
stand-in core: the request each sends, what it prints on which stream and its exit code (spec:
cli; perform-status-logs design D14; worktree-stage design D6; unit-tests-cli-commands-config-init
design D1-D3).

Each result and update is the protocol's own message, in the shapes the core returned for a
scripted actor's run in a git theatre (its startedBy made anonymous). The lines the CLI takes from
troupe.cli.render are built with it here; that module's tests pin their text. Their tests that
start a process, open a socket or use a git theatre are in integration/."""

import base64
import copy
import io
import json
from pathlib import Path
from typing import Any

import pytest

from cli_core_stand_in import StandIn, stand_in
from troupe.cli.commands import _write_exactly
from troupe.cli.render import (
    render_audit,
    render_gate,
    render_log_entry,
    render_run,
    render_run_line,
)
from troupe.core.client.messages import (
    AcceptResult,
    DiffResult,
    DiscardResult,
    LoggedEvent,
    LoggedNotice,
    LogsResult,
    NoticeUpdate,
    StatusResult,
)
from troupe.core.exit_codes import ExitCode

RUN_ID = "57468ead-167b-4c35-887e-1af08e16144c"
SHORT = "57468ead"
BASE = "06e610bf0077235089a2da29b9fbc7fafd000c2a"
WORKTREE = f".troupe/local/worktrees/{RUN_ID}"
EMPTY = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
DIFF = "sha256:2f743dfc4438f26e732e5e3af0a9c8b6d90289a70ea6983bd659db36e6bfef35"
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
    "stage": {
        "name": "local",
        "effects": "unenforced",
        "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
    },
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
RECORDED: dict[str, Any] = {
    "kind": "run-notice",
    "runId": RUN_ID,
    "at": "2026-11-26T06:56:23.950Z",
    "notice": {"code": "run.silent", "problem": "Quiet.", "fix": "Wait."},
}
NOTICE = {"code": "config.waiting", "problem": "Waiting.", "fix": "Wait.", "details": {}}
NOTICE_LINES = ["troupe: Waiting.", "  fix: Wait."]
OUTSIDE = {"outside": [{"path": "src/a.py", "change": "modified", "needs": "write"}]}


def _run(**fields: Any) -> dict[str, Any]:  # noqa: ANN401
    run = {**copy.deepcopy(RUN), **fields}
    for name in [name for name, value in fields.items() if value is None]:
        del run[name]
    return run


RUNNING = _run(
    workspace={"kind": "theatre"},
    changes=None,
    approvers=None,
    state="running",
    outcome=None,
    endedAt=None,
    transcript=None,
    transcriptFormat=None,
    stderr=None,
    audit=None,
)


def _status(
    *runs: dict[str, Any],
    notices: tuple[dict[str, Any], ...] = (),
    cues: tuple[dict[str, Any], ...] = (),
) -> StatusResult:
    return StatusResult.from_data(
        {"runs": list(runs), "cues": list(cues), "notices": list(notices)}
    )


def _logs(run: dict[str, Any], log: list[dict[str, Any]], *notices: dict[str, Any]) -> LogsResult:
    return LogsResult.from_data({"run": run, "log": log, "notices": list(notices)})


def _entry(data: dict[str, Any]) -> LoggedEvent | LoggedNotice:
    return (
        LoggedNotice.from_data(data)
        if data["kind"] == "run-notice"
        else LoggedEvent.from_data(data)
    )


@pytest.fixture
def core(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> StandIn:
    return stand_in(monkeypatch, tmp_path)


# status


def test_status_lists_each_run_on_a_line(core: StandIn) -> None:
    core.reply("status", _status(_run(), RUNNING, notices=(NOTICE,)))
    ran = core.run("status")
    assert core.requests == [("status", {})]
    assert ran.code == ExitCode.OK
    assert ran.out == [render_run_line(_run()), render_run_line(RUNNING)]
    assert ran.err == NOTICE_LINES


def test_status_with_a_limit_sends_it(core: StandIn) -> None:
    core.reply("status", _status(_run()))
    core.run("status", "--limit", "3")
    assert core.requests == [("status", {"limit": 3})]


def test_status_of_one_run_prints_its_summary(core: StandIn) -> None:
    core.reply("status", _status(_run()))
    ran = core.run("status", SHORT)
    assert core.requests == [("status", {"run": SHORT})]
    assert ran.out == render_run(_run())


def test_status_with_no_runs_says_so(core: StandIn) -> None:
    core.reply("status", _status())
    assert core.run("status").out == ["No runs yet."]


def test_status_as_json_prints_the_result_on_one_line(core: StandIn) -> None:
    core.reply("status", _status(_run(actor="lead"), notices=(NOTICE,)))
    ran = core.run("status", "--json")
    assert ran.out == [json.dumps(_status(_run(), notices=(NOTICE,)).to_data())]
    assert ran.err == NOTICE_LINES


def test_status_as_json_keeps_non_ascii(core: StandIn) -> None:
    notice = {"at": "2026-11-26T06:56:23.950Z", "notice": {**NOTICE, "problem": "Café."}}
    core.reply("status", _status(_run(notices=[notice])))
    assert "Café." in core.run("status", "--json").stdout


# logs


def test_logs_prints_the_log_then_the_runs_outcome(core: StandIn) -> None:
    log = [EVENTS[0], RECORDED, EVENTS[1]]
    core.reply("logs", _logs(_run(), log, NOTICE))
    ran = core.run("logs", SHORT)
    assert core.requests == [("logs", {"run": SHORT})]
    assert ran.code == ExitCode.OK
    assert ran.out == [
        *(render_log_entry(entry) for entry in log),
        f"run {RUN_ID}: succeeded",
        *render_audit(_run()),
        *render_gate(_run()),
    ]
    assert ran.err == NOTICE_LINES


def test_logs_of_a_running_run_names_its_state(core: StandIn) -> None:
    core.reply("logs", _logs(RUNNING, []))
    assert core.run("logs", SHORT).out == [f"run {RUN_ID}: running"]


def test_logs_names_a_renamed_actor_and_the_audit(core: StandIn) -> None:
    run = _run(actorNow="star", audit=OUTSIDE)
    core.reply("logs", _logs(run, []))
    ran = core.run("logs", SHORT)
    assert ran.out == [
        f"run {RUN_ID}: succeeded",
        "  actor: lead (now star)",
        *render_audit(run),
        *render_gate(run),
    ]
    assert len(render_audit(run)) > 0


def test_followed_entries_are_shown_as_they_come_and_not_again(core: StandIn) -> None:
    log = [EVENTS[0], RECORDED, EVENTS[1]]
    core.reply(
        "logs",
        _logs(_run(), log),
        _entry(EVENTS[0]),
        _entry(RECORDED),
        NoticeUpdate.from_data({"kind": "notice", "notice": NOTICE}),
    )
    ran = core.run("logs", SHORT, "--follow")
    assert core.requests == [("logs", {"run": SHORT, "follow": True})]
    assert ran.out == [
        render_log_entry(EVENTS[0]),
        render_log_entry(RECORDED),
        render_log_entry(EVENTS[1]),
        f"run {RUN_ID}: succeeded",
        *render_audit(_run()),
        *render_gate(_run()),
    ]
    assert ran.err == NOTICE_LINES


def test_logs_as_json_prints_each_update_then_the_result(core: StandIn) -> None:
    notice = {"kind": "notice", "notice": NOTICE}
    core.reply(
        "logs",
        _logs(_run(), [EVENTS[0]], NOTICE),
        _entry(EVENTS[0]),
        NoticeUpdate.from_data(notice),
    )
    ran = core.run("logs", SHORT, "--json", "--follow")
    assert [json.loads(line) for line in ran.out] == [
        EVENTS[0],
        notice,
        _logs(_run(), [EVENTS[0]], NOTICE).to_data(),
    ]
    assert ran.err == NOTICE_LINES


def test_logs_as_json_keeps_non_ascii(core: StandIn) -> None:
    event = copy.deepcopy(EVENTS[1])
    event["event"]["message"] = "wrote café.md"
    core.reply("logs", _logs(_run(), [event]), _entry(event))
    ran = core.run("logs", SHORT, "--json")
    assert ran.stdout.count("café") == 2


def test_ctrl_c_while_following_stops_following_and_exits_cancelled(core: StandIn) -> None:
    core.reply("logs", _logs(RUNNING, []), presses=1)
    ran = core.run("logs", SHORT, "--follow")
    assert ran.logged == ()  # no error from the Ctrl-C handler
    assert core.calls[0].session.cancel.requested
    assert ran.code == ExitCode.CANCELLED
    assert ran.out == [f"run {RUN_ID}: running"]
    assert ran.stderr == ""


# diff


def _diff(patch: str | None = None, encoding: str | None = None) -> DiffResult:
    data: dict[str, Any] = {"run": RUN_ID, "base": BASE, "changes": PENDING}
    if patch is not None:
        data |= {"patch": patch, "encoding": encoding}
    return DiffResult.from_data(data)


PATCH = (
    "diff --git a/AUDITION.md b/AUDITION.md\nnew file mode 100644\n--- /dev/null\n"
    "+++ b/AUDITION.md\n"
)


def test_diff_prints_a_utf8_patch_exactly(core: StandIn) -> None:
    core.reply("diff", _diff(PATCH + "+café\n", "utf-8"))
    ran = core.run("diff", SHORT)
    assert core.requests == [("diff", {"run": SHORT})]
    assert ran.code == ExitCode.OK
    assert ran.stdout == PATCH + "+café\n"


def test_diff_decodes_a_base64_patch(core: StandIn) -> None:
    raw = PATCH.encode() + b"+\xff\n"
    core.reply("diff", _diff(base64.b64encode(raw).decode("ascii"), "base64"))
    ran = core.run("diff", SHORT)
    assert ran.stdout == raw.decode("utf-8", "surrogateescape")


def test_diff_of_a_run_that_changed_nothing_says_so(core: StandIn) -> None:
    core.reply("diff", _diff())
    ran = core.run("diff", SHORT)
    assert ran.code == ExitCode.OK
    assert ran.stdout == ""
    assert ran.err == [f"troupe: run {SHORT} changed nothing."]


def test_diff_as_json_prints_the_result(core: StandIn) -> None:
    core.reply("diff", _diff(PATCH + "+é\n", "utf-8"))
    ran = core.run("diff", SHORT, "--json")
    assert ran.out == [json.dumps(_diff(PATCH + "+é\n", "utf-8").to_data(), ensure_ascii=False)]


class _Binary(io.TextIOWrapper):
    """A text stream over bytes, as standard output is."""


def test_a_patch_goes_to_a_streams_bytes_untranslated() -> None:
    raw = io.BytesIO()
    stream = _Binary(raw, encoding="utf-8", newline="\r\n")
    stream.write("before ")
    _write_exactly(b"a\nb\xff", stream)
    assert raw.getvalue() == b"before a\nb\xff"


# accept and discard


def test_accept_lists_the_files_it_unstaged(core: StandIn) -> None:
    result = {"run": RUN_ID, "files": ["AUDITION.md", "b.md"], "rehearsed": False, "notices": []}
    core.reply(
        "accept",
        AcceptResult.from_data(result),
        NoticeUpdate.from_data({"kind": "notice", "notice": NOTICE}),
    )
    ran = core.run("accept", SHORT, "--reason", "good")
    assert core.requests == [("accept", {"run": SHORT, "reason": "good"})]
    assert ran.code == ExitCode.OK
    assert ran.out == [f"run {RUN_ID} accepted, unstaged:", "  AUDITION.md", "  b.md"]
    assert ran.err == NOTICE_LINES


def test_a_rehearsed_accept_says_what_it_would_change(core: StandIn) -> None:
    result = {"run": RUN_ID, "files": ["AUDITION.md"], "rehearsed": True, "notices": []}
    core.reply("accept", AcceptResult.from_data(result))
    ran = core.run("accept", SHORT, "--rehearse")
    assert core.requests == [("accept", {"run": SHORT, "rehearse": True})]
    assert ran.code == ExitCode.WOULD_CHANGE
    assert ran.out == [f"accepting run {RUN_ID} would change:", "  AUDITION.md"]


def test_discard_says_what_it_removed_and_what_it_leaves(core: StandIn) -> None:
    result = {"run": RUN_ID, "worktree": WORKTREE, "rehearsed": False, "notices": []}
    core.reply(
        "discard",
        DiscardResult.from_data(result),
        NoticeUpdate.from_data({"kind": "notice", "notice": NOTICE}),
    )
    ran = core.run("discard", SHORT, "--reason", "bad")
    assert core.requests == [("discard", {"run": SHORT, "reason": "bad"})]
    assert ran.code == ExitCode.OK
    assert ran.out == [f"run {RUN_ID} discarded: removed {WORKTREE}"]
    assert ran.err == [
        *NOTICE_LINES,
        "troupe: discarding removes files, not git state: any branches, tags, stashes, config or "
        "hooks the run made are still there (troupe status shows what it saw change).",
    ]


def test_a_rehearsed_discard_says_what_it_would_remove(core: StandIn) -> None:
    result = {"run": RUN_ID, "worktree": WORKTREE, "rehearsed": True, "notices": []}
    core.reply("discard", DiscardResult.from_data(result))
    ran = core.run("discard", SHORT, "--rehearse")
    assert core.requests == [("discard", {"run": SHORT, "rehearse": True})]
    assert ran.code == ExitCode.WOULD_CHANGE
    assert ran.out == [f"discarding run {RUN_ID} would remove {WORKTREE}"]
    assert ran.stderr == ""


# What every query and settle command does while the core runs it


def _result(method: str) -> Any:  # noqa: ANN401
    return {
        "status": _status(_run()),
        "logs": _logs(_run(), []),
        "diff": _diff(),
        "accept": AcceptResult.from_data(
            {"run": RUN_ID, "files": ["a.md"], "rehearsed": False, "notices": []}
        ),
        "discard": DiscardResult.from_data(
            {"run": RUN_ID, "worktree": WORKTREE, "rehearsed": False, "notices": []}
        ),
    }[method]


@pytest.mark.parametrize("method", ["status", "diff", "accept", "discard"])
def test_ctrl_c_during_a_command_that_cant_be_cancelled_changes_nothing(
    core: StandIn, method: str
) -> None:
    argv = (method,) if method == "status" else (method, SHORT)
    core.reply(method, _result(method))
    calm = core.run(*argv)
    core.reply(method, _result(method), presses=1)
    pressed = core.run(*argv)
    assert pressed == calm
    assert core.calls[1].session.cancel.requested
    assert core.calls[1].session.theatre == Path.cwd()


# Requirement: Approve and reject commands (spec: gates)


def test_approve_sends_the_run_and_reason_and_lists_the_files_it_kept(core: StandIn) -> None:
    result = {"run": RUN_ID, "files": ["AUDITION.md"], "rehearsed": False, "notices": []}
    core.reply("approve", AcceptResult.from_data(result))
    ran = core.run("approve", SHORT, "--reason", "fine")
    assert core.requests == [("approve", {"run": SHORT, "reason": "fine"})]
    assert ran.code == ExitCode.OK
    assert ran.out == [f"run {RUN_ID} approved, its changes kept, unstaged:", "  AUDITION.md"]


def test_a_rehearsed_approve_says_what_it_would_change_and_exits_would_change(
    core: StandIn,
) -> None:
    result = {"run": RUN_ID, "files": ["AUDITION.md"], "rehearsed": True, "notices": []}
    core.reply("approve", AcceptResult.from_data(result))
    ran = core.run("approve", SHORT, "--rehearse")
    assert core.requests == [("approve", {"run": SHORT, "rehearse": True})]
    assert ran.code == ExitCode.WOULD_CHANGE
    assert ran.out == [f"approving run {RUN_ID} would change:", "  AUDITION.md"]


def test_reject_says_what_it_removed_and_what_it_leaves(core: StandIn) -> None:
    result = {"run": RUN_ID, "worktree": WORKTREE, "rehearsed": False, "notices": []}
    core.reply("reject", DiscardResult.from_data(result))
    ran = core.run("reject", SHORT, "--reason", "wrong file")
    assert core.requests == [("reject", {"run": SHORT, "reason": "wrong file"})]
    assert ran.code == ExitCode.OK
    assert ran.out == [f"run {RUN_ID} rejected: removed {WORKTREE}"]
    assert ran.err[-1].startswith("troupe: rejecting removes files, not git state")


def test_a_rehearsed_reject_names_the_worktree_and_exits_would_change(core: StandIn) -> None:
    result = {"run": RUN_ID, "worktree": WORKTREE, "rehearsed": True, "notices": []}
    core.reply("reject", DiscardResult.from_data(result))
    ran = core.run("reject", SHORT, "--rehearse")
    assert ran.code == ExitCode.WOULD_CHANGE
    assert ran.out == [f"rejecting run {RUN_ID} would remove {WORKTREE}"]


# Requirement: Status shows open cues and a run's gate (spec: gates)


def test_status_shows_each_open_cue_before_the_runs(core: StandIn) -> None:
    cue = {
        "run": RUN_ID,
        "actor": "writer",
        "role": "director",
        "raisedAt": "2026-11-26T07:00:00.000Z",
    }
    core.reply("status", _status(_run(), cues=(cue,)))
    ran = core.run("status")
    assert ran.out[0] == (
        f"waiting: run {SHORT} of writer for director, since 2026-11-26T07:00:00.000Z: "
        f"troupe approve {SHORT} or troupe reject {SHORT}"
    )
    assert ran.out[1:] == [render_run_line(_run())]


def test_a_waiting_run_is_shown_as_waiting_in_the_list(core: StandIn) -> None:
    waiting = {
        **PENDING,
        "state": "waiting",
        "cue": {"role": "director", "raisedAt": "2026-11-26T07:00:00.000Z"},
    }
    line = render_run_line(_run(changes=waiting))
    assert f"{RUN_ID}  succeeded, waiting" in line


def test_status_of_a_run_shows_its_approvers(core: StandIn) -> None:
    core.reply("status", _status(_run()))
    ran = core.run("status", SHORT)
    assert "  approvers: troupe, director (default)" in ran.out
