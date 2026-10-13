"""troupe perform, status and logs on the command line (spec: cli; perform-status-logs design D3,
D4, D14)."""

import importlib
import io
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from client_schemas import check
from gitrepo import Repo
from runtesting import ADA, ALLOW, INIT, OK, script, theatre, turn
from storetesting import git_service
from test_run_queries import Child
from troupe.cli import COMMANDS, commands, main
from troupe.cli.parser import parse
from troupe.cli.render import render_run
from troupe.core.client import messages as m
from troupe.core.errors import TroupeError

# troupe.core.runs re-exports perform the function, so the module is reached by name.
PERFORM = importlib.import_module("troupe.core.runs.perform")
ALLOWANCE = {"setting": "allow_unenforced_local_stage", "source": "env"}

TROUPE = [sys.executable, "-c", "import sys; from troupe.cli import main; sys.exit(main())"]


def cli(*argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    """A git theatre as the working directory, with ada acting and the local stage allowed."""
    made = theatre(tmp_path)
    for name, value in {**made.env, **ADA, **ALLOW}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(made.path)
    return made


def options_file(repo: Repo, options: dict[str, Any], name: str = "script.json") -> str:
    path = repo.path / name
    path.write_text(json.dumps(options), encoding="utf-8")
    return name


def started(repo: Repo, run_id: str) -> dict[str, Any]:
    first = git_service(repo).history(UUID(run_id))[0]
    state: dict[str, Any] = json.loads(first.state)
    return state


# 10.2: perform's command line.


def usage_code(*argv: str) -> str:
    with pytest.raises(TroupeError) as caught:
        parse(list(argv), COMMANDS)
    return caught.value.code


def test_perform_needs_one_of_expect_or_no_effect_check(repo: Repo) -> None:
    argv = ("perform", "tester", "--runner", "scripted")
    code, out, err = cli(*argv)
    assert (code, out) == (2, "")
    assert usage_code(*argv) == "usage.missing-one-of"
    assert "needs one of --expect or --no-effect-check" in err


def test_perform_refuses_both_effect_check_flags(repo: Repo) -> None:
    argv = ("perform", "tester", "--runner", "scripted", "--expect", "a", "--no-effect-check")
    code, _, err = cli(*argv)
    assert code == 2
    assert usage_code(*argv) == "usage.conflicting-options"
    assert "takes --expect or --no-effect-check, not both" in err


def test_perform_needs_a_runner(repo: Repo) -> None:
    argv = ("perform", "tester", "--no-effect-check")
    code, _, err = cli(*argv)
    assert code == 2
    assert usage_code(*argv) == "usage.missing-argument"
    assert "needs --runner" in err


def test_an_unknown_runner_is_refused_naming_the_known_ones(repo: Repo) -> None:
    code, out, err = cli("perform", "tester", "--runner", "claude", "--no-effect-check")
    assert code == 1
    assert out == ""
    assert "'claude'" in err
    assert "scripted" in err


@pytest.mark.parametrize(
    ("content", "said"),
    [
        ("[1, 2]", "a JSON list, not an object"),
        ('{"script": 1, "script": 2}', "appears more than once"),
        ('{"x": NaN}', "NaN"),
        ("{not json", "isn't strict JSON"),
    ],
    ids=["array", "duplicate key", "NaN", "not JSON"],
)
def test_runner_options_that_arent_a_json_object_are_refused_naming_the_file(
    repo: Repo, content: str, said: str
) -> None:
    (repo.path / "bad.json").write_text(content, encoding="utf-8")
    code, out, err = cli(
        "perform",
        "tester",
        "--runner",
        "scripted",
        "--runner-options",
        "bad.json",
        "--no-effect-check",
    )
    assert code == 1
    assert out == ""
    assert said in err
    assert "bad.json" in err


def test_a_missing_runner_options_file_is_refused(repo: Repo) -> None:
    code, _, err = cli(
        "perform",
        "tester",
        "--runner",
        "scripted",
        "--runner-options",
        "nope.json",
        "--no-effect-check",
    )
    assert code == 1
    assert "couldn't be read" in err


def test_an_expected_path_is_read_from_the_working_directory(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    write = {"writeFile": {"path": "src/out.txt", "content": "hi"}}
    name = options_file(repo, script(INIT, write, OK))
    (repo.path / "src").mkdir()
    monkeypatch.chdir(repo.path / "src")
    code, out, _ = cli(
        "perform",
        "tester",
        "--runner",
        "scripted",
        "--runner-options",
        f"../{name}",
        "--expect",
        "out.txt",
    )
    assert code == 0
    run_id = out.split()[1]
    assert started(repo, run_id)["effect_check"] == {"kind": "files", "paths": ["src/out.txt"]}


@pytest.mark.parametrize("path", ["../elsewhere.txt", "."], ids=["outside", "the theatre itself"])
def test_an_expected_path_outside_the_theatre_is_refused(repo: Repo, path: str) -> None:
    code, out, err = cli("perform", "tester", "--runner", "scripted", "--expect", path)
    assert code == 2
    assert out == ""
    assert f"--expect {path}" in err


def test_with_no_theatre_perform_fails_naming_the_directory_and_creates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()
    monkeypatch.chdir(nowhere)
    code, out, err = cli("perform", "tester", "--runner", "scripted", "--no-effect-check")
    assert code == 1
    assert out == ""
    assert "no .troupe directory" in err
    assert list(nowhere.iterdir()) == []


def test_a_success_prints_progress_on_stderr_and_only_the_result_on_stdout(repo: Repo) -> None:
    name = options_file(repo, script(INIT, turn("hello there"), OK))
    code, out, err = cli(
        "perform", "tester", "--runner", "scripted", "--runner-options", name, "--no-effect-check"
    )
    assert code == 0
    run_id = out.split()[1]
    assert out == f"run {run_id} succeeded\n"
    lines = err.splitlines()
    assert lines[0].startswith(f"troupe: run {run_id} starting")
    assert any("init: scripted 0.1.0" in line for line in lines)
    assert any("turn: assistant: hello there" in line for line in lines)
    assert lines.index(next(line for line in lines if "init:" in line)) > 0


def test_a_failed_run_leaves_stdout_empty_and_shows_the_error_with_the_run_id(repo: Repo) -> None:
    error = {"event": {"type": "result", "status": "error", "message": "it broke"}}
    name = options_file(repo, script(INIT, error))
    code, out, err = cli(
        "perform", "tester", "--runner", "scripted", "--runner-options", name, "--no-effect-check"
    )
    assert code == 1
    assert out == ""
    assert "The runner reported an error: it broke" in err
    assert "  fix: " in err
    assert "(failed)" in err
    assert "  run: " in err


def test_the_default_policy_refuses_the_local_stage_naming_the_variable(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE")
    code, out, err = cli("perform", "tester", "--runner", "scripted", "--no-effect-check")
    assert code == 1
    assert out == ""
    assert "TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true" in err


def test_perform_as_a_real_process_records_the_run_in_the_theatre(repo: Repo) -> None:
    name = options_file(repo, script(INIT, OK))
    done = subprocess.run(
        [
            *TROUPE,
            "perform",
            "tester",
            "--runner",
            "scripted",
            "--runner-options",
            name,
            "--no-effect-check",
        ],
        cwd=repo.path,
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    run_id = done.stdout.split()[1]
    topics = [r.topic.split(":")[1] for r in git_service(repo).history(UUID(run_id))]
    assert topics == ["Run.Started", "Run.Reported", "Run.Reported", "Run.Ended"]


# 10.4: status and logs.


def performed(repo: Repo, options: dict[str, Any]) -> str:
    name = options_file(repo, options)
    code, out, err = cli(
        "perform", "tester", "--runner", "scripted", "--runner-options", name, "--no-effect-check"
    )
    assert code == 0, err
    return out.split()[1]


def test_status_json_is_the_status_result_as_its_schema_shapes_it(repo: Repo) -> None:
    run_id = performed(repo, script(INIT, OK))
    for argv in (("status", "--json"), ("status", run_id[:8], "--json")):
        code, out, _ = cli(*argv)
        assert code == 0
        assert "null" not in out
        result = json.loads(out)
        check(result, "status-result.schema.json")
        assert [r["runId"] for r in result["runs"]] == [run_id]


def test_status_json_for_a_run_whose_runner_never_started_has_no_null_and_validates(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(PERFORM, "runner_command", lambda _: ["troupe-no-such-runner"])
    name = options_file(repo, script(INIT, OK))
    code, out, err = cli(
        "perform", "tester", "--runner", "scripted", "--runner-options", name, "--no-effect-check"
    )
    assert code == 1
    assert out == ""
    assert "(could-not-start)" in err
    run_id = err.split("  run: ")[1].split()[0]
    code, out, _ = cli("status", run_id, "--json")
    assert code == 0
    assert "null" not in out
    result = json.loads(out)
    check(result, "status-result.schema.json")
    [run] = result["runs"]
    assert run["outcome"] == "could-not-start"
    assert "transcript" not in run
    assert "stderr" not in run
    assert "reported" not in run["runner"]
    code, out, _ = cli("status", run_id)
    assert "outcome: could-not-start" in out
    assert "error: runner.start-failed" in out
    assert "transcript:" not in out
    assert "stderr:" not in out


def test_a_running_runs_summary_renders_no_outcome_end_transcript_or_stderr() -> None:
    summary = m.RunSummary.from_data(
        {
            "runId": "0f8fad5b-d9cb-469f-a165-70867728950e",
            "actor": "tester",
            "startedBy": {"kind": "human", "id": "ada@example.com", "source": "env"},
            "runner": {"requested": "scripted"},
            "stage": {"name": "local", "effects": "unenforced", "allowedBy": ALLOWANCE},
            "effectCheck": {"kind": "none"},
            "state": "running",
            "events": 0,
            "startedAt": "2026-10-13T00:00:00.000Z",
        }
    )
    lines = render_run(summary.to_data())
    assert "  runner: scripted" in lines
    assert "  outcome: -" in lines
    assert not [line for line in lines if line.startswith(("  ended", "  transcript", "  stderr"))]


def test_status_shows_one_run_and_lists_runs(repo: Repo) -> None:
    run_id = performed(repo, script(INIT, OK))
    code, out, _ = cli("status", run_id)
    assert code == 0
    assert f"run {run_id}" in out
    assert "outcome: succeeded" in out
    code, out, _ = cli("status")
    assert out.startswith(run_id)
    assert "succeeded" in out


def test_status_with_no_runs_says_so(repo: Repo) -> None:
    assert cli("status") == (0, "No runs yet.\n", "")


def test_status_with_a_run_and_a_limit_is_a_usage_error(repo: Repo) -> None:
    run_id = performed(repo, script(INIT, OK))
    code, out, err = cli("status", run_id, "--limit", "2")
    assert code == 2
    assert out == ""
    assert "not both" in err


def test_logs_json_is_the_logs_result_as_its_schema_shapes_it(repo: Repo) -> None:
    run_id = performed(repo, script(INIT, turn("a"), OK))
    code, out, _ = cli("logs", run_id, "--json")
    assert code == 0
    result = json.loads(out)
    check(result, "logs-result.schema.json")
    assert [e["seq"] for e in result["events"]] == [0, 1, 2]


def test_logs_follow_json_writes_each_update_on_a_line_then_the_result(repo: Repo) -> None:
    run_id = performed(repo, script(INIT, OK))
    code, out, _ = cli("logs", run_id, "--follow", "--json")
    assert code == 0
    *updates, last = out.splitlines()
    for line in updates:
        check(json.loads(line), "logs-update.schema.json")
    assert len(updates) == 2
    check(json.loads(last), "logs-result.schema.json")


def test_logs_shows_events_on_stdout_and_notices_on_stderr(repo: Repo, tmp_path: Path) -> None:
    child = Child(repo, script(INIT, {"hang": True}))
    child.kill()
    code, out, err = cli("logs", child.run_id)
    assert code == 0
    assert "init: scripted 0.1.0" in out
    assert out.splitlines()[-1] == f"run {child.run_id}: interrupted"
    assert "has no recorded end" in err
    assert "has no recorded end" not in out


def test_the_help_lists_perform_status_and_logs(repo: Repo) -> None:
    code, out, _ = cli("--help")
    assert code == 0
    for name in ("perform", "status", "logs"):
        assert name in out


# 10.3 and 10.4, end to end: real processes, Ctrl-C, another terminal.


class Process:
    """troupe running as a real process, its standard error read line by line as it comes."""

    def __init__(self, repo: Repo, *argv: str) -> None:
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP
        self.process = subprocess.Popen(
            [*TROUPE, *argv],
            cwd=repo.path,
            env=dict(os.environ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=flags,
        )
        self.lines: queue.Queue[str] = queue.Queue()
        self.seen: list[str] = []
        assert self.process.stderr is not None
        stderr = self.process.stderr
        threading.Thread(target=self._read, args=(stderr,), daemon=True).start()

    def _read(self, stream: Any) -> None:  # noqa: ANN401
        for line in stream:
            self.lines.put(line)

    def wait_for(self, text: str, timeout: float = 60) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=0.5)
            except queue.Empty:
                continue
            self.seen.append(line)
            if text in line:
                return line
        raise AssertionError(f"{text!r} never appeared; saw {self.seen}")

    def interrupt(self) -> None:
        if sys.platform == "win32":
            self.process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            self.process.send_signal(signal.SIGINT)

    def finish(self, timeout: float = 60) -> tuple[int, str]:
        assert self.process.stdout is not None
        out = self.process.stdout.read()
        code = self.process.wait(timeout=timeout)
        while not self.lines.empty():
            self.seen.append(self.lines.get())
        return code, out


def test_one_ctrl_c_cancels_the_run_records_cancelled_and_exits_130(repo: Repo) -> None:
    name = options_file(repo, script(INIT, {"hang": True}))
    troupe = Process(
        repo,
        "perform",
        "tester",
        "--runner",
        "scripted",
        "--runner-options",
        name,
        "--no-effect-check",
    )
    run_id = troupe.wait_for("starting").split()[2]
    troupe.wait_for("init:")
    troupe.interrupt()
    code, out = troupe.finish()
    assert code == 130
    assert out == ""
    assert sum("Cancelling the run" in line for line in troupe.seen) == 1
    [run] = json.loads(cli("status", run_id, "--json")[1])["runs"]
    assert (run["state"], run["outcome"]) == ("ended", "cancelled")


def test_ctrl_c_twice_shows_the_notice_twice_and_still_records_the_end(repo: Repo) -> None:
    name = options_file(repo, script(INIT, {"hang": True}, on_cancel="ignore"))
    troupe = Process(
        repo,
        "perform",
        "tester",
        "--runner",
        "scripted",
        "--runner-options",
        name,
        "--no-effect-check",
    )
    run_id = troupe.wait_for("starting").split()[2]
    troupe.wait_for("init:")
    troupe.interrupt()
    troupe.wait_for("Cancelling the run")
    time.sleep(0.5)
    troupe.interrupt()
    troupe.wait_for("already cancelling")
    code, _ = troupe.finish(timeout=120)
    assert code == 130
    [run] = json.loads(cli("status", run_id, "--json")[1])["runs"]
    assert (run["state"], run["outcome"]) == ("ended", "cancelled")


def test_logs_follow_in_another_process_shows_a_running_runs_events_and_exits_0_at_its_end(
    repo: Repo,
) -> None:
    slow = script(INIT, {"wait": {"ms": 1500}}, turn("later"), OK)
    name = options_file(repo, slow)
    troupe = Process(
        repo,
        "perform",
        "tester",
        "--runner",
        "scripted",
        "--runner-options",
        name,
        "--no-effect-check",
    )
    run_id = troupe.wait_for("starting").split()[2]
    troupe.wait_for("init:")
    follow = subprocess.run(
        [*TROUPE, "logs", run_id[:8], "--follow"],
        cwd=repo.path,
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert troupe.finish()[0] == 0
    assert follow.returncode == 0, follow.stderr
    assert "turn: assistant: later" in follow.stdout
    assert follow.stdout.splitlines()[-1] == f"run {run_id}: succeeded"


def test_each_ctrl_c_during_perform_announces_cancelling_and_counts_the_presses(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The real Ctrl-C is sent in a subprocess (test_platform_interrupts and below); here the core
    # call is stood in for, so the notice perform prints is checked in this process.
    def call(*args: object) -> dict[str, Any]:
        on_cancel: Callable[[int], None] = args[-1]  # type: ignore[assignment]
        on_cancel(1)
        on_cancel(2)
        return {"run": {"runId": "0f8fad5b-d9cb-469f-a165-70867728950e", "outcome": "cancelled"}}

    monkeypatch.setattr(commands, "_call", call)
    name = options_file(repo, script(INIT, OK))
    code, _, err = cli(
        "perform", "tester", "--runner", "scripted", "--runner-options", name, "--no-effect-check"
    )
    assert code == 130
    assert err.count("Cancelling the run") == 2
    assert "troupe is already cancelling it." in err
