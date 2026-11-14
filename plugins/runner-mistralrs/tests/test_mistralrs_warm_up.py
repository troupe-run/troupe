"""Run with --warm-up, the runner warms its engine outside any run and says how in one JSON line
(spec: mistralrs-runner, "The runner warms its engine when troupe asks, outside any run";
in-process-runner design D4)."""

import io
import json
import sys

import pytest

from stand_in import StandIn
from test_mistralrs_before_ack import METAL_FAILURE
from troupe_runner_mistralrs.runner import warm_up


def _warm(check: object, platform: str, monkeypatch: pytest.MonkeyPatch) -> tuple[int, object]:
    monkeypatch.setattr(sys, "platform", platform)
    out = io.BytesIO()
    times = iter([10.0, 27.25])
    code = warm_up(check, out, lambda: next(times))  # type: ignore[arg-type]
    (line,) = out.getvalue().splitlines()
    return code, json.loads(line)


def test_on_macos_it_loads_the_check_model_and_says_how_long_it_took(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked: list[bool] = []
    code, answer = _warm(lambda: checked.append(True), "darwin", monkeypatch)
    assert (code, answer) == (0, {"warmedUp": True, "seconds": 17.2})
    assert checked == [True]


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_elsewhere_there_is_nothing_to_warm_and_nothing_is_loaded(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    def no_load() -> None:
        raise AssertionError("loaded a model")

    assert _warm(no_load, platform, monkeypatch) == (0, {"warmedUp": False})


def test_a_python_the_engine_cant_run_under_is_the_platform_checks_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, answer = _warm(StandIn({"check": {"error": METAL_FAILURE}}).check, "darwin", monkeypatch)
    assert code == 1
    assert isinstance(answer, dict)
    error = answer["error"]
    assert error["code"] == "mistralrs.unsupported-python"
    assert "uv tool install --managed-python" in error["fix"]
    assert error["details"]["python"] == sys.executable
