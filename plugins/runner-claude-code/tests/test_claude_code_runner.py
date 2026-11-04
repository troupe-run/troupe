"""The Claude Code runner's process, driven over pipes with the stand-in claude on its PATH (spec:
claude-code-runner; design D2, D3, D6, D7)."""

import json
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_harness import FIXTURES, Session, alive, recording, wait_for_record
from fake_claude import install
from troupe_plugin_sdk.declaration import posix_absolute

FIXED = ["-p", "--output-format", "stream-json", "--verbose", "--no-session-persistence"]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "workspace"
    path.mkdir()
    return path


@pytest.fixture
def record(tmp_path: Path) -> Path:
    return tmp_path / "record.json"


def _env(tmp_path: Path, record: Path, **fake: str) -> dict[str, str]:
    """The runner's environment: a PATH holding only the stand-in, and the stand-in's settings."""
    install(tmp_path / "bin")
    env = {"PATH": str(tmp_path / "bin"), "FAKE_CLAUDE_RECORD": str(record)}
    for name in ("COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR"):
        if name in os.environ:
            env[name] = os.environ[name]
    env.update({f"FAKE_CLAUDE_{name.upper()}": value for name, value in fake.items()})
    return env


def _fixture(name: str) -> str:
    return str(FIXTURES / name / "recording.jsonl")


def _lines_file(tmp_path: Path, *lines: object) -> str:
    path = tmp_path / "lines.txt"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return str(path)


INIT_LINE = {
    "type": "system",
    "subtype": "init",
    "tools": ["Read"],
    "model": "m",
    "claude_code_version": "9.9.9",
}


@pytest.fixture
def sessions() -> Iterator[list[Session]]:
    started: list[Session] = []
    yield started
    for session in started:
        session.kill()


def _session(sessions: list[Session], workspace: Path, env: dict[str, str]) -> Session:
    session = Session(workspace, env)
    sessions.append(session)
    return session


def _notifications(messages: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (m["method"], {k: v for k, v in m["params"].items() if k not in ("runId", "seq")})
        for m in messages
        if "method" in m
    ]


def _until_result(session: Session) -> list[dict[str, Any]]:
    """Every message up to and including the result event."""
    messages = []
    while True:
        message = session.message()
        messages.append(message)
        if message.get("method") == "run/event" and message["params"]["type"] == "result":
            return messages


def test_the_handshake_names_claude_code_its_version_and_no_capabilities(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    session = _session(sessions, workspace, _env(tmp_path, record))
    answer = session.initialize()
    assert answer["result"] == {
        "protocolVersion": 0,
        "runner": {"name": "claude-code", "version": "0.0.1.dev0"},
        "capabilities": [],
    }
    session.validate_all()


def test_a_handshake_offering_no_supported_version_is_refused_naming_version_0(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    session = _session(sessions, workspace, _env(tmp_path, record))
    answer = session.initialize([7])
    assert answer["error"]["data"]["code"] == "runner.unsupported-version"
    assert answer["error"]["data"]["details"] == {"supportedVersions": [0]}


def test_with_no_claude_on_its_path_run_start_is_refused_naming_the_path(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    env = {**_env(tmp_path, record), "PATH": str(tmp_path / "empty")}
    session = _session(sessions, workspace, env)
    answer = session.start()
    assert answer["error"]["data"]["code"] == "claude-code.not-found"
    assert answer["error"]["data"]["details"] == {"path": str(tmp_path / "empty")}
    assert "Install Claude Code" in answer["error"]["data"]["fix"]
    assert not record.exists()
    session.validate_all()


def test_with_no_path_at_all_run_start_is_refused_saying_so(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    env = _env(tmp_path, record)
    del env["PATH"]
    session = _session(sessions, workspace, env)
    answer = session.start()
    assert answer["error"]["data"]["code"] == "claude-code.not-found"
    assert answer["error"]["data"]["details"] == {}
    assert "no PATH" in answer["error"]["data"]["problem"]


def test_an_unknown_option_is_refused_and_no_claude_starts(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    session = _session(sessions, workspace, _env(tmp_path, record))
    answer = session.start({"troupeConformanceUnknownOption": True}, valid=False)
    assert answer["error"]["data"]["code"] == "claude-code.unknown-option"
    assert answer["error"]["data"]["details"] == {"where": "options.troupeConformanceUnknownOption"}
    assert not record.exists()
    session.validate_all()


def test_a_malformed_option_is_refused_naming_it(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    session = _session(sessions, workspace, _env(tmp_path, record))
    answer = session.start({"permissionMode": "yolo"}, valid=False)
    assert answer["error"]["data"]["code"] == "claude-code.invalid-options"
    assert answer["error"]["data"]["details"] == {"where": "options.permissionMode"}
    session.validate_all()


def test_a_workspace_that_doesnt_exist_is_refused(
    tmp_path: Path, record: Path, sessions: list[Session]
) -> None:
    session = _session(sessions, tmp_path, _env(tmp_path, record))
    session.workspace = tmp_path / "missing"
    answer = session.start()
    assert answer["error"]["data"]["code"] == "claude-code.start-failed"
    session.validate_all()


def test_a_second_run_start_is_refused(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    session = _session(sessions, workspace, _env(tmp_path, record, hang="1"))
    session.start()
    answer = session.request(
        "run/start",
        {
            "runId": session.run_id,
            "direction": "again",
            "workspace": str(workspace),
            "options": {},
            "limits": {"eventMaxBytes": 65536},
            "effects": {"write": [], "delete": [], "move": []},
            "scratch": str(session.scratch()),
        },
    )
    assert answer["error"]["data"]["code"] == "runner.already-started"


def test_killing_a_session_mid_run_ends_the_runner_and_its_hanging_stand_in(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    # spec: claude-code-runner, "The runner's tests stop it as troupe would" (reap-fake-claude D1)
    session = _session(sessions, workspace, _env(tmp_path, record, hang="1"))
    session.start()
    second = session.request(
        "run/start",
        {
            "runId": session.run_id,
            "direction": "again",
            "workspace": str(workspace),
            "options": {},
            "limits": {"eventMaxBytes": 65536},
            "effects": {"write": [], "delete": [], "move": []},
            "scratch": str(session.scratch()),
        },
    )
    assert second["error"]["data"]["code"] == "runner.already-started"
    stand_in = wait_for_record(record, "pid")["pid"]
    session.kill()
    assert not alive(session.process.pid)
    deadline = time.monotonic() + 30
    while alive(stand_in) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not alive(stand_in)


def test_claude_runs_in_the_workspace_with_the_fixed_flags_and_the_direction_on_stdin(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    session = _session(
        sessions, workspace, _env(tmp_path, record, fixture=_fixture("success-with-tools"))
    )
    direction = 'say "hi"\nthen stop'
    session.start(direction=direction)
    seen = wait_for_record(record, "argv")
    assert seen["argv"][: len(FIXED)] == FIXED
    rest = seen["argv"][len(FIXED) :]
    assert rest[:-2] == [
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--max-budget-usd",
        "5",
        "--permission-mode",
        "dontAsk",
        "--add-dir",
        str(session.scratch()),
    ]
    assert rest[-2] == "--settings"
    assert seen["stdin"] == direction
    assert Path(seen["cwd"]).resolve() == workspace.resolve()
    assert not any("hi" in arg for arg in seen["argv"])
    assert seen["env"]["DISABLE_AUTOUPDATER"] == "1"
    assert seen["env"]["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"


def test_the_character_and_tool_rules_reach_claude_in_private_files_removed_afterwards(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    session = _session(
        sessions, workspace, _env(tmp_path, record, fixture=_fixture("success-with-tools"))
    )
    options = {"allowedTools": ["Bash(git status)", "Read"], "settingSources": ["project"]}
    session.start(options, character="You test carefully.")
    _until_result(session)
    session.request("shutdown", {})
    assert session.wait() == 0
    seen = wait_for_record(record, "files")
    argv = seen["argv"]
    assert argv[argv.index("--setting-sources") + 1] == "project"
    assert seen["files"]["--append-system-prompt-file"] == "You test carefully."
    root, scratch = posix_absolute(workspace), posix_absolute(session.scratch())
    assert json.loads(seen["files"]["--settings"]) == {
        "permissions": {
            "allow": ["Bash(git status)", "Read", f"Edit(/{scratch}/**)"],
            "deny": [f"Edit(/{root}/.git/**)", f"Edit(/{root}/.troupe/**)"],
        },
        "sandbox": {"autoAllowBashIfSandboxed": False},
    }
    private = Path(argv[argv.index("--settings") + 1]).parent
    assert not private.resolve().is_relative_to(workspace.resolve())
    assert not private.exists()
    session.validate_all()


@pytest.mark.parametrize("name", sorted(path.name for path in FIXTURES.iterdir() if path.is_dir()))
def test_each_fixture_through_the_runner_gives_its_transcript_and_events_in_order(
    name: str, tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    expected = json.loads((FIXTURES / name / "expected.json").read_text(encoding="utf-8"))
    env = _env(tmp_path, record, fixture=_fixture(name), exit=str(expected["exitCode"]))
    session = _session(sessions, workspace, env)
    session.start()
    has_result = any(line.get("event", {}).get("type") == "result" for line in recording(name))
    if has_result:
        messages = _until_result(session)
        session.request("shutdown", {})
    else:
        messages = session.rest()
    want = [
        ("run/transcript", {"record": line["transcript"]})
        if "transcript" in line
        else ("run/event", {k: v for k, v in line["event"].items() if k not in ("runId", "seq")})
        for line in recording(name)
    ]
    got = _notifications(messages)
    for index, (method, params) in enumerate(got):
        if method == "run/event" and params["type"] == "init":
            got[index] = (
                method,
                {**params, "runner": {"name": "claude-code", "version": "unreleased"}},
            )
    assert got == want
    seqs = [m["params"]["seq"] for m in messages if m.get("method") == "run/event"]
    assert seqs == list(range(len(seqs)))
    assert session.wait() == expected["exitCode"]
    if not has_result:
        assert b"and sent no result" in session.stderr()
    session.validate_all()


def test_claude_exiting_before_its_init_gives_a_synthetic_init_a_log_and_no_result(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    session = _session(sessions, workspace, _env(tmp_path, record, exit="1"))
    session.start()
    events = [m["params"] for m in session.rest() if m.get("method") == "run/event"]
    assert [e["type"] for e in events] == ["init", "log"]
    assert "engine" not in events[0]
    assert events[1]["level"] == "error"
    assert "exit code 1" in events[1]["message"]
    assert session.wait() == 1
    session.validate_all()


def test_an_ok_result_then_exit_1_makes_the_runner_exit_non_zero(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    env = _env(tmp_path, record, fixture=_fixture("success-with-tools"), exit="1")
    session = _session(sessions, workspace, env)
    session.start()
    _until_result(session)
    assert session.request("shutdown", {})["result"] == {}
    assert session.wait() == 1
    assert b"Claude Code exited with code 1" in session.stderr()


def test_claudes_standard_error_reaches_the_runners(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    env = _env(tmp_path, record, fixture=_fixture("success-with-tools"), stderr="node warning: x\n")
    session = _session(sessions, workspace, env)
    session.start()
    _until_result(session)
    session.request("shutdown", {})
    assert b"node warning: x\n" in session.stderr()


def _hanging_after_init(tmp_path: Path, record: Path) -> dict[str, str]:
    return _env(tmp_path, record, fixture=_lines_file(tmp_path, INIT_LINE), hang="1")


def test_cancel_mid_run_stops_claude_before_the_runner_exits_and_sends_no_more_events(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    session = _session(sessions, workspace, _hanging_after_init(tmp_path, record))
    session.start(character="c")
    while (message := session.message()).get("method") != "run/event":
        pass
    assert message["params"]["type"] == "init"
    seen = wait_for_record(record, "argv")
    assert session.request("run/cancel", {"runId": session.run_id})["result"] == {}
    rest = session.rest()
    assert [m for m in rest if m.get("method") == "run/event"] == []
    assert session.wait() == 0
    assert not alive(seen["pid"])
    private = Path(seen["argv"][seen["argv"].index("--append-system-prompt-file") + 1]).parent
    assert not private.exists()
    session.validate_all()


def test_end_of_input_mid_run_stops_claude_and_then_the_runner_exits(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    session = _session(sessions, workspace, _hanging_after_init(tmp_path, record))
    session.start(character="c")
    seen = wait_for_record(record, "argv")
    session.close_stdin()
    assert session.wait() == 0
    assert not alive(seen["pid"])
    private = Path(seen["argv"][seen["argv"].index("--append-system-prompt-file") + 1]).parent
    assert not private.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="the exit status of a SIGTERM is POSIX's")
def test_claude_terminated_by_someone_else_ends_the_run_with_no_result(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    import signal

    session = _session(sessions, workspace, _hanging_after_init(tmp_path, record))
    session.start()
    while (message := session.message()).get("method") != "run/event":
        pass
    assert message["params"]["type"] == "init"
    assert message["params"]["engine"]["version"] == "9.9.9"  # Claude Code's, not a synthetic init
    seen = wait_for_record(record, "argv")
    os.kill(seen["pid"], signal.SIGTERM)
    assert [m for m in session.rest() if m.get("method") == "run/event"] == []
    assert session.wait() == 143
    assert b"Claude Code exited with code 143 and sent no result" in session.stderr()


@pytest.mark.skipif(sys.platform == "win32", reason="a missing interpreter is how POSIX fails exec")
def test_a_claude_that_cant_be_started_gives_a_synthetic_init_a_log_and_exit_1(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    env = _env(tmp_path, record)
    broken = tmp_path / "broken"
    broken.mkdir()
    claude = broken / "claude"
    claude.write_text("#!/nonexistent/interpreter\n", encoding="utf-8")
    claude.chmod(0o755)
    env["PATH"] = str(broken)
    session = _session(sessions, workspace, env)
    assert session.start()["result"] == {"runId": session.run_id}
    events = [m["params"] for m in session.rest() if m.get("method") == "run/event"]
    assert [e["type"] for e in events] == ["init", "log"]
    assert events[1]["level"] == "error"
    assert "couldn't be started" in events[1]["message"]
    assert session.wait() == 1
    session.validate_all()


# Requirement: Options can't widen the effects; A pattern Claude Code would read differently is
# refused (declared-effects design D8)


def test_an_actor_that_accepts_edits_is_refused_saying_to_declare_effects(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    session = _session(sessions, workspace, _env(tmp_path, record))
    answer = session.start({"permissionMode": "acceptEdits"}, valid=False)
    data = answer["error"]["data"]
    assert data["code"] == "claude-code.widens-effects"
    assert data["details"] == {"where": "options.permissionMode"}
    assert "effects.write" in data["fix"]
    assert not record.exists()  # no Claude Code started
    session.validate_all()


def test_an_allowed_edit_rule_is_refused_naming_it(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    session = _session(sessions, workspace, _env(tmp_path, record))
    answer = session.start({"allowedTools": ["Edit(src/**)"]}, valid=False)
    data = answer["error"]["data"]
    assert data["code"] == "claude-code.widens-effects"
    assert data["details"] == {"where": "options.allowedTools[0]"}
    assert "'Edit(src/**)'" in data["problem"]
    session.validate_all()


def test_a_write_pattern_with_a_bracket_is_refused_naming_it(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    session = _session(sessions, workspace, _env(tmp_path, record))
    answer = session.start(effects={"write": ["app/[id]/page.tsx"]})
    data = answer["error"]["data"]
    assert data["code"] == "claude-code.untranslatable-pattern"
    assert data["details"] == {"where": "effects.write"}
    assert "'app/[id]/page.tsx'" in data["problem"]
    assert "'['" in data["problem"]
    assert not record.exists()


# Requirement: Write effects become edit rules; What the translation can't cover is said


def test_write_effects_reach_claude_as_edit_rules_and_init_says_translated(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    session = _session(
        sessions, workspace, _env(tmp_path, record, fixture=_fixture("success-with-tools"))
    )
    session.start(effects={"write": ["out/**"]})
    messages = _until_result(session)
    events = [m["params"] for m in messages if m.get("method") == "run/event"]
    assert events[0]["type"] == "init"
    assert events[0]["effects"] == "translated"
    seen = wait_for_record(record, "files")
    settings = json.loads(seen["files"]["--settings"])
    root = posix_absolute(workspace)
    assert f"Edit(/{root}/out/**)" in settings["permissions"]["allow"]
    assert "--mcp-config" not in seen["argv"]


def test_an_allowed_shell_rule_and_loaded_settings_are_warned_about_before_the_result(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    session = _session(
        sessions, workspace, _env(tmp_path, record, fixture=_fixture("success-with-tools"))
    )
    session.start({"allowedTools": ["Bash(uv run pytest *)"], "settingSources": ["project"]})
    messages = _until_result(session)
    events = [m["params"] for m in messages if m.get("method") == "run/event"]
    warnings = [e["message"] for e in events if e["type"] == "log" and e["level"] == "warning"]
    assert any("'Bash(uv run pytest *)'" in w and "audit" in w for w in warnings)
    assert any("project settings" in w for w in warnings)
    assert events[-1]["type"] == "result"


# Requirement: Delete and move effects are troupe's own tools


def test_declaring_delete_starts_claude_with_troupes_mcp_server(
    tmp_path: Path, workspace: Path, record: Path, sessions: list[Session]
) -> None:
    session = _session(
        sessions, workspace, _env(tmp_path, record, fixture=_fixture("success-with-tools"))
    )
    session.start(effects={"delete": ["drafts/**"]})
    _until_result(session)
    seen = wait_for_record(record, "argv")
    argv = seen["argv"]
    config = Path(argv[argv.index("--mcp-config") + 1])
    assert config.name == "mcp.json"
    assert not config.resolve().is_relative_to(workspace.resolve())
