"""A run's summary in troupe status and logs, one fact per line, and its line in a list of runs
(spec: cli, "Status and logs commands" and "Status and logs show a run's audit"). Each summary is
checked against the protocol's RunSummary first, so the lines are those of a shape troupe really
sends."""

import copy
from typing import Any

import pytest

from troupe.cli.render import render_audit, render_run, render_run_line
from troupe.core.client import messages as m

RUN_ID = "0193a4c2-7f1e-7b55-9c1d-2a6f0e3b8d41"
BASE = "0123456789abcdef0123456789abcdef01234567"
TRANSCRIPT = "sha256:" + "a" * 64
STDERR = "sha256:" + "c" * 64
DIFF = "sha256:" + "d" * 64
WORKTREE = ".troupe/worktrees/01JDXQ7Z3K"

ENDED: dict[str, Any] = {
    "runId": RUN_ID,
    "actor": "tester",
    "startedBy": {"kind": "human", "id": "ada@example.com", "source": "git"},
    "runner": {"requested": "scripted", "reported": {"name": "fake-runner", "version": "1.2.3"}},
    "stage": {"name": "worktree", "effects": "enforced"},
    "effectCheck": {"kind": "none"},
    "workspace": {"kind": "worktree", "path": WORKTREE, "base": BASE, "dirty": False},
    "changes": {"state": "pending", "diff": DIFF, "worktree": WORKTREE},
    "approvers": {"value": ["troupe", "director"], "source": "default"},
    "state": "ended",
    "outcome": "failed",
    "events": 42,
    "startedAt": "2026-11-21T09:14:02.000Z",
    "endedAt": "2026-11-21T09:16:40.000Z",
    "transcript": TRANSCRIPT,
    "transcriptFormat": "native",
    "audit": {"outside": []},
}


def _run(**fields: Any) -> dict[str, Any]:  # noqa: ANN401
    data = {**copy.deepcopy(ENDED), **fields}
    for name in [name for name, value in fields.items() if value is None]:
        del data[name]
    m.RunSummary.from_data(data)  # a shape troupe sends
    return data


def test_the_summary_of_an_ended_worktree_run_with_every_line() -> None:
    run = _run(
        actorNow="qa",
        workspace={"kind": "worktree", "path": WORKTREE, "base": BASE, "dirty": True},
        error={"code": "runner.failed", "problem": "It stopped.", "fix": "Look."},
        transcriptFormat="kinds",
        stderr=STDERR,
        recording={"error": {"code": "store.full", "problem": "p", "fix": "f"}, "failedAt": 7},
        notices=[
            {
                "at": "2026-11-21T09:15:00.000Z",
                "notice": {"code": "run.silent", "problem": "Quiet.\nLong.", "fix": "Wait."},
            }
        ],
    )
    assert render_run(run) == [
        f"run {RUN_ID}",
        "  actor: tester (now qa)",
        "  started by: ada@example.com at 2026-11-21T09:14:02.000Z",
        "  runner: scripted (fake-runner 1.2.3)",
        "  stage: worktree, effects enforced",
        "  workspace: its own worktree at 0123456789ab, the theatre had uncommitted changes it "
        "didn't see",
        "  state: ended",
        "  outcome: failed",
        "  events: 42",
        "  error: runner.failed: It stopped.",
        "  audit: every change the run made was declared",
        "  ended: 2026-11-21T09:16:40.000Z",
        f"  transcript: {TRANSCRIPT} (kinds)",
        f"  stderr: {STDERR}",
        "  recording stopped at event 7: store.full",
        "  changes: pending",
        f"  diff: {DIFF}",
        f"  worktree: {WORKTREE}",
        "  approvers: troupe, director (default)",
        "  notices:",
        "    2026-11-21T09:15:00.000Z run.silent: Quiet.",
    ]


def test_the_summary_of_a_running_theatre_run_started_by_no_one_known() -> None:
    run = _run(
        startedBy={"kind": "unknown"},
        runner={"requested": "scripted"},
        stage={
            "name": "local",
            "effects": "unenforced",
            "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
        },
        workspace={"kind": "theatre"},
        changes=None,
        approvers=None,
        state="running",
        outcome=None,
        endedAt=None,
        transcript=None,
        transcriptFormat=None,
        audit=None,
        events=3,
    )
    assert render_run(run) == [
        f"run {RUN_ID}",
        "  actor: tester",
        "  started by: unknown at 2026-11-21T09:14:02.000Z",
        "  runner: scripted",
        "  stage: local, effects unenforced",
        "  workspace: the theatre",
        "  state: running",
        "  outcome: -",
        "  events: 3",
    ]


def test_a_worktree_from_a_clean_theatre_names_only_its_base() -> None:
    assert "  workspace: its own worktree at 0123456789ab" in render_run(_run())


def test_a_recording_that_stopped_at_a_notice_names_the_notice() -> None:
    recording = {
        "error": {"code": "store.full", "problem": "p", "fix": "f"},
        "notice": "run.silent",
    }
    assert "  recording stopped at notice run.silent: store.full" in render_run(
        _run(recording=recording)
    )


def _changes_lines(changes: dict[str, Any]) -> list[str]:
    lines = render_run(_run(changes=changes))
    # Up to the approvers line, which every worktree run's summary ends its changes with.
    return lines[lines.index(f"  transcript: {TRANSCRIPT}") + 1 : -1]


def test_pending_changes_name_their_counts_and_what_was_left_out() -> None:
    changes = {
        "state": "pending",
        "diff": DIFF,
        "worktree": WORKTREE,
        "added": 3,
        "modified": 2,
        "deleted": 1,
        "leftOut": 4,
    }
    assert _changes_lines(changes) == [
        "  changes: pending (3 added, 2 modified, 1 deleted, 4 under .troupe/ left out)",
        f"  diff: {DIFF}",
        f"  worktree: {WORKTREE}",
    ]


def test_changes_with_nothing_left_out_do_not_say_so() -> None:
    changes = {
        "state": "pending",
        "diff": DIFF,
        "worktree": WORKTREE,
        "added": 0,
        "modified": 5,
        "deleted": 0,
        "leftOut": 0,
    }
    assert _changes_lines(changes)[0] == "  changes: pending (0 added, 5 modified, 0 deleted)"


def test_settled_changes_say_when_and_shared_changes_are_named_by_kind() -> None:
    changes = {
        "state": "accepted",
        "diff": DIFF,
        "settledAt": "2026-11-21T10:00:00.000Z",
        "shared": {
            "refs": [
                {"name": "refs/heads/main", "change": "changed"},
                {"name": "refs/tags/v1", "change": "added"},
            ],
            "hooks": [{"name": "pre-commit", "change": "removed"}],
        },
    }
    assert _changes_lines(changes) == [
        "  changes: accepted at 2026-11-21T10:00:00.000Z",
        f"  diff: {DIFF}",
        "  changed in git while it ran (refs): refs/heads/main changed, refs/tags/v1 added",
        "  changed in git while it ran (hooks): pre-commit removed",
    ]


def test_changes_that_could_not_be_captured_name_the_error() -> None:
    changes = {
        "state": "uncaptured",
        "worktree": WORKTREE,
        "error": {"code": "vcs.failed", "problem": "git broke", "fix": "f"},
    }
    assert _changes_lines(changes) == [
        "  changes: uncaptured",
        f"  worktree: {WORKTREE}",
        "  capture failed: vcs.failed: git broke",
    ]


# The audit of a run's changes.


def _audit(outside: list[dict[str, Any]], workspace: str = "worktree") -> list[str]:
    fields: dict[str, Any] = {"audit": {"outside": outside}}
    if workspace == "theatre":
        fields |= {"workspace": {"kind": "theatre"}, "changes": None, "approvers": None}
    return render_audit(_run(**fields))


def test_one_change_outside_the_declaration_is_named() -> None:
    outside = [{"path": "src/a.py", "change": "modified", "needs": "write"}]
    assert _audit(outside) == [
        "  audit: 1 change outside the declaration",
        "    src/a.py modified (needs write)",
    ]


def test_changes_outside_the_declaration_in_the_theatre_say_anyone_may_have_made_them() -> None:
    outside = [
        {"path": "a.txt", "change": "removed", "needs": "delete"},
        {"path": "b.txt", "change": "moved", "needs": "move", "to": "c.txt"},
    ]
    assert _audit(outside, workspace="theatre") == [
        "  audit: 2 changes outside the declaration",
        "    a.txt removed (needs delete)",
        "    b.txt moved to c.txt (needs move)",
        "    A run in the theatre counts every change made there while it ran, by anyone.",
    ]


def test_an_audit_that_could_not_run_names_the_error() -> None:
    error = {"code": "vcs.failed", "problem": "no tree", "fix": "f"}
    assert render_audit(_run(audit={"error": error})) == [
        "  audit couldn't run: vcs.failed: no tree"
    ]


def test_a_run_with_no_audit_shows_none() -> None:
    run = _run(audit=None, transcript=None, transcriptFormat=None)
    assert render_audit(run) == []


# A run's line in a list of runs.


@pytest.mark.parametrize(
    ("fields", "line"),
    [
        (
            {},
            f"{RUN_ID}  failed               tester           2026-11-21T09:14:02.000Z  42 events",
        ),
        (
            {"actorNow": "qa", "events": 1},
            f"{RUN_ID}  failed               tester (now qa)  2026-11-21T09:14:02.000Z  1 events",
        ),
        (
            {
                "notices": [
                    {
                        "at": "2026-11-21T09:15:00.000Z",
                        "notice": {"code": "run.silent", "problem": "p", "fix": "f"},
                    }
                ]
            },
            f"{RUN_ID}  failed               tester           2026-11-21T09:14:02.000Z  42 events, "
            "1 notice",
        ),
    ],
    ids=["ended", "renamed since", "one notice"],
)
def test_a_list_line_shows_the_outcome_actor_start_and_counts(
    fields: dict[str, Any], line: str
) -> None:
    assert render_run_line(_run(**fields)) == line


def test_a_list_line_of_a_run_still_going_shows_its_state() -> None:
    run = _run(
        state="running",
        outcome=None,
        endedAt=None,
        transcript=None,
        transcriptFormat=None,
        audit=None,
    )
    assert render_run_line(run).startswith(f"{RUN_ID}  running              tester ")


# Requirement: A run's summary shows its gate (spec: runs, cli; manual-gates)


def test_a_runs_gate_steps_follow_its_approvers_in_order() -> None:
    at = "2026-11-21T09:17:00.000Z"
    run = _run(
        changes={"state": "accepted", "settledAt": at, "files": ["src/a.txt"]},
        gate=[
            {
                "step": "passed",
                "approver": "troupe",
                "to": "director",
                "files": ["src/a.txt"],
                "at": at,
            },
            {"step": "cue", "role": "director", "at": at},
            {
                "step": "approved",
                "role": "director",
                "actor": {"kind": "human", "id": "ada@example.com", "source": "vcs"},
                "reason": "fine",
                "at": at,
            },
        ],
    )
    lines = render_run(run)
    start = lines.index("  approvers: troupe, director (default)")
    assert lines[start + 1 : start + 4] == [
        f"  gate: troupe passed to director at {at}: src/a.txt conflicts with your files",
        f"  gate: cue for director at {at}",
        f"  gate: approved by ada@example.com as director at {at}: fine",
    ]


def test_troupes_own_approval_names_it_by_its_system_id() -> None:
    at = "2026-11-21T09:17:00.000Z"
    run = _run(
        changes={"state": "accepted", "settledAt": at, "files": ["src/a.txt"]},
        gate=[
            {
                "step": "approved",
                "role": "troupe",
                "actor": {"kind": "system", "id": "core@build-01"},
                "at": at,
            }
        ],
    )
    assert f"  gate: approved by core@build-01 as troupe at {at}" in render_run(run)


def test_waiting_changes_name_the_role_they_wait_for() -> None:
    waiting = {
        "state": "waiting",
        "diff": DIFF,
        "worktree": WORKTREE,
        "cue": {"role": "director", "raisedAt": "2026-11-21T09:17:00.000Z"},
    }
    assert "  changes: waiting for director" in render_run(_run(changes=waiting))
