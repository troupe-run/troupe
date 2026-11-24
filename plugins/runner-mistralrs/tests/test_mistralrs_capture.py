"""The capture tool, run end to end with the engine stand-in serving each fixture's recorded
responses, writes that fixture again: the same run, responses, token counts and expected events. So
a fresh capture from a real model gives what the replay compares, the runner's version included
(spec: mistralrs-runner, "Fixtures pair real engine output with protocol events")."""

import contextlib
import datetime
import hashlib
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from mistralrs_fixtures_shared import CASES, FIXTURES, _capture, _filled, _load
from stand_in import StandIn

MODEL = "Qwen3-0.6B-Q8_0.gguf"
REWRITTEN = ("run.json", "responses.json", "engine.json", "expected.json")


def _replaying(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: str
) -> tuple[ModuleType, Path, Path]:
    """The capture tool, writing under ``tmp_path``, with its run's workspace and scratch at
    known paths and the engine stand-in serving ``case``'s recorded responses. Returns the tool,
    the model file and the directory the fixtures are written to."""
    capture = _capture()
    workspace, scratch, out = tmp_path / "w", tmp_path / "s", tmp_path / "fixtures"
    for directory in (workspace, scratch, out):
        directory.mkdir()
    workspace, scratch = workspace.resolve(), scratch.resolve()
    directories = iter((workspace, scratch))

    def temporary_directory() -> contextlib.AbstractContextManager[str]:
        return contextlib.nullcontext(str(next(directories)))

    engine = _load(case, "engine.json")
    stand_in = StandIn(
        {
            "responses": _filled(_load(case, "responses.json"), str(workspace), str(scratch)),
            "maxSequenceLength": engine["maxSequenceLength"],
            "counts": engine["counts"],
            "paths": {"<workspace>": str(workspace), "<scratch>": str(scratch)},
        }
    )
    monkeypatch.setattr(
        capture, "tempfile", SimpleNamespace(TemporaryDirectory=temporary_directory)
    )
    monkeypatch.setattr(capture.engine, "load", stand_in.load)
    monkeypatch.setattr(capture, "FIXTURES", out)
    model = tmp_path / MODEL
    model.write_bytes(b"a stand-in for the model's file")
    return capture, model, out


def _written(directory: Path, name: str) -> Any:  # noqa: ANN401 - JSON
    return json.loads((directory / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES)
def test_a_capture_with_the_stand_in_writes_its_fixture_again(
    case: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture, model, out = _replaying(monkeypatch, tmp_path, case)
    capture.capture(model, case)
    written = out / case
    for name in REWRITTEN:
        assert _written(written, name) == _load(case, name), name
    events = _written(written, "expected.json")["events"]
    (init,) = [event for event in events if event["type"] == "init"]
    assert init["runner"]["version"] == "<package version>"
    provenance = _written(written, "provenance.json")
    recorded = _load(case, "provenance.json")
    assert provenance["mistralrs"] == recorded["mistralrs"]
    assert provenance["model"] == MODEL
    assert provenance["sha256"] == hashlib.sha256(model.read_bytes()).hexdigest()
    assert provenance["date"] == datetime.date.today().isoformat()


def test_the_tool_captures_the_cases_its_command_line_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    capture, model, out = _replaying(monkeypatch, tmp_path, "tool-call")
    monkeypatch.setattr(sys, "argv", ["capture_mistralrs.py", str(model), "tool-call"])
    capture.main()
    assert [path.name for path in out.iterdir()] == ["tool-call"]
    assert _written(out / "tool-call", "expected.json") == _load("tool-call", "expected.json")
    assert capsys.readouterr().out.startswith("tool-call: ")


def test_the_tool_has_a_case_for_each_fixture() -> None:
    assert sorted(_capture().CASES) == CASES
    assert all((FIXTURES / case / "provenance.json").exists() for case in CASES)


def test_a_count_for_a_windows_path_written_into_json_is_recorded_under_its_placeholder() -> None:
    # The tool definitions are counted as JSON, which doubles a Windows path's backslashes. The
    # capture must record the count under the key the replay looks it up by.
    capture = _capture()
    scratch = "C:\\Users\\runner\\AppData\\Local\\Temp\\s"
    inner = SimpleNamespace(count=lambda text: 1160)
    recording = capture.Recording(inner, "C:\\Users\\runner\\AppData\\Local\\Temp\\w", scratch)
    assert recording.count(json.dumps({"scratch": scratch}, separators=(",", ":"))) == 1160
    key = hashlib.sha256(b'{"scratch":"<scratch>"}').hexdigest()
    assert recording.counts == {key: 1160}
