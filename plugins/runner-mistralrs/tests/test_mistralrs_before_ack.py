"""What the runner checks before it acknowledges a run, without loading the run's model (spec:
mistralrs-runner, "The runner's options are closed", "The model comes from the run's in-process
runtime", "The model is a local GGUF file", "The runner checks its engine's version against
published data", "An unsupported macOS Python is refused before the run is acknowledged", "The
runner publishes its schemas"; in-process-runner design D4)."""

import io
import json
import math
import sys
import threading
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from hypothesis import given
from hypothesis import strategies as st

from mistralrs_harness import (
    CHECK_MODEL,
    OWN,
    RUNNER_SCHEMAS,
    drive,
    initialize,
    own_validator,
    run_start,
    start_message,
)
from stand_in import StandIn
from troupe_runner_mistralrs.options import OptionsError, parse_options
from troupe_runner_mistralrs.port import LoadSpec
from troupe_runner_mistralrs.requirements import load
from troupe_runner_mistralrs.runner import Runner

METAL_FAILURE = (
    "Metal error Error while loading library: Error while loading library: program_source:318:14: "
    "error: constructor for 'BlockMMA<float, float, 32, 32, 16, 2, 2, false, false, 20, 36>' must "
    "explicitly initialize the member 'Asimd' which does not have a default constructor"
)


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    workspace, scratch = tmp_path / "w", tmp_path / "s"
    workspace.mkdir()
    scratch.mkdir()
    return workspace, scratch


def _answer(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """run/start's answer."""
    return next(m for m in messages if m.get("id") == 2)


def _refused(params: dict[str, Any], **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
    loads: list[LoadSpec] = []
    stand_in = StandIn({})

    def loader(spec: LoadSpec) -> Any:  # noqa: ANN401
        loads.append(spec)
        return stand_in.load(spec)

    kwargs.setdefault("loader", loader)
    answer = _answer(drive([initialize(), start_message(params)], **kwargs))
    assert "error" in answer, answer
    assert loads == []  # nothing is loaded before a refusal
    data: dict[str, Any] = answer["error"]["data"]
    return data


# Requirement: The runner's options are closed


def test_an_unknown_option_is_refused_naming_it(dirs: tuple[Path, Path]) -> None:
    options = {"troupeConformanceUnknownOption": True}
    error = _refused(run_start(*dirs, str(CHECK_MODEL), options=options))
    assert error["code"] == "mistralrs.unknown-option"
    assert error["details"] == {"where": "options.troupeConformanceUnknownOption"}


def test_a_model_in_the_options_is_refused_saying_its_the_runtimes(dirs: tuple[Path, Path]) -> None:
    error = _refused(run_start(*dirs, str(CHECK_MODEL), options={"model": "/m.gguf"}))
    assert error["code"] == "mistralrs.unknown-option"
    assert error["details"] == {"where": "options.model"}
    assert "TROUPE_RUNTIME_MISTRALRS_MODEL" in error["problem"]


@pytest.mark.parametrize("options", [{"maxTurns": 0}, {"contextLength": "large"}, {"think": "x"}])
def test_a_malformed_value_is_refused_naming_it_and_what_is_valid(
    dirs: tuple[Path, Path], options: dict[str, Any]
) -> None:
    error = _refused(run_start(*dirs, str(CHECK_MODEL), options=options))
    assert error["code"] == "mistralrs.invalid-options"
    assert error["details"] == {"where": f"options.{next(iter(options))}"}


OPTION_VALUES = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-5, max_value=2**65),
    st.sampled_from([10**400, -(10**400)]),  # past a float's range: a JSON reader takes them
    st.floats(allow_nan=True, allow_infinity=True),
    st.text(max_size=5),
)


@pytest.mark.parametrize("option", ["temperature", "seed", "maxTurns", "contextLength"])
@pytest.mark.parametrize("value", [10**400, -(10**400)])
def test_an_integer_past_a_floats_range_is_refused_as_an_invalid_option(
    option: str, value: int
) -> None:
    # A JSON reader takes a 400-digit integer; comparing it as a float would overflow.
    with pytest.raises(OptionsError):
        parse_options({option: value})


@given(
    st.dictionaries(
        st.sampled_from(["maxTurns", "contextLength", "temperature", "seed", "think", "other"]),
        OPTION_VALUES,
        max_size=4,
    )
)
def test_the_parser_and_the_published_schema_accept_and_refuse_the_same_options(
    options: dict[str, Any],
) -> None:
    try:
        parse_options(options)
        parsed = True
    except OptionsError:
        parsed = False
    if any(isinstance(v, float) and not math.isfinite(v) for v in options.values()):
        assert not parsed  # NaN and infinities aren't JSON numbers: never a valid option
        return
    assert parsed == own_validator("options.schema.json").is_valid(options)


def test_each_schema_is_draft_2020_12_with_an_id_under_the_plugin() -> None:
    for name in ("options.schema.json", "errors.schema.json"):
        schema = json.loads((RUNNER_SCHEMAS / name).read_text(encoding="utf-8"))
        assert schema["$id"] == OWN + name
        jsonschema.Draft202012Validator.check_schema(schema)


# Requirement: The model comes from the run's in-process runtime


def test_a_run_without_a_runtime_is_refused_saying_to_name_mistralrs(
    dirs: tuple[Path, Path],
) -> None:
    params = run_start(*dirs, str(CHECK_MODEL))
    del params["runtime"]
    error = _refused(params)
    assert error["code"] == "mistralrs.no-runtime"
    assert "actors.<name>.runtime=mistralrs" in error["fix"]


def test_a_runtime_with_an_endpoint_is_refused_naming_it(dirs: tuple[Path, Path]) -> None:
    params = run_start(*dirs, str(CHECK_MODEL))
    params["runtime"]["endpoint"] = "http://127.0.0.1:11434"
    error = _refused(params)
    assert error["code"] == "mistralrs.invalid-runtime"
    assert error["details"] == {"where": "runtime.endpoint"}


def test_a_runtime_with_a_credential_is_refused_holding_none_of_it(
    dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    canary = "sk-canary-q7ZxW9pL4vR2"
    monkeypatch.setenv("TROUPE_RUNTIME_CREDENTIAL", canary)
    params = run_start(*dirs, str(CHECK_MODEL))
    params["runtime"]["credential"] = True
    error = _refused(params)
    assert error["code"] == "mistralrs.invalid-runtime"
    assert error["details"] == {"where": "runtime.credential"}
    assert canary not in json.dumps(error)


# Requirement: The model is a local GGUF file


def test_a_model_name_rather_than_a_file_is_refused_and_nothing_is_fetched(
    dirs: tuple[Path, Path],
) -> None:
    error = _refused(run_start(*dirs, "Qwen/Qwen3-0.6B-GGUF"))
    assert error["code"] == "mistralrs.invalid-model"
    assert error["details"] == {"where": "runtime.model", "model": "Qwen/Qwen3-0.6B-GGUF"}
    assert "absolute path" in error["problem"]
    assert "TROUPE_RUNTIME_MISTRALRS_MODEL" in error["fix"]


def test_a_file_that_isnt_there_is_refused_naming_the_path(
    dirs: tuple[Path, Path], tmp_path: Path
) -> None:
    missing = str(tmp_path / "missing.gguf")
    error = _refused(run_start(*dirs, missing))
    assert error["code"] == "mistralrs.model-not-found"
    assert missing in error["problem"]


def test_a_file_that_isnt_gguf_is_refused_saying_so(
    dirs: tuple[Path, Path], tmp_path: Path
) -> None:
    text = tmp_path / "notes.txt"
    text.write_text("not a model", encoding="utf-8")
    error = _refused(run_start(*dirs, str(text)))
    assert error["code"] == "mistralrs.invalid-model"
    assert "isn't a GGUF file" in error["problem"]


# Requirement: The runner checks its engine's version against published data


def test_the_published_requirement_is_mistralrs_0_9_5() -> None:
    (requirement,) = load()
    assert (requirement.name, requirement.version) == ("mistralrs", "0.9.5")
    assert requirement.why


def test_another_installed_version_is_refused_naming_both(dirs: tuple[Path, Path]) -> None:
    error = _refused(run_start(*dirs, str(CHECK_MODEL)), versions=lambda name: "0.9.4")
    assert error["code"] == "runner.requirement-unmet"
    assert error["details"] == {"requirement": "mistralrs", "wanted": "0.9.5", "found": "0.9.4"}


# Requirement: An unsupported macOS Python is refused before the run is acknowledged


def test_metal_kernels_that_dont_compile_are_refused_pointing_to_a_uv_managed_python(
    dirs: tuple[Path, Path],
) -> None:
    stand_in = StandIn({"check": {"error": METAL_FAILURE}})
    error = _refused(run_start(*dirs, str(CHECK_MODEL)), check=stand_in.check)
    assert error["code"] == "mistralrs.unsupported-python"
    assert error["details"]["python"] == sys.executable
    assert "uv tool install --managed-python" in error["fix"]


def test_another_check_failure_is_refused_as_an_unmet_requirement(
    dirs: tuple[Path, Path],
) -> None:
    stand_in = StandIn({"check": {"error": "something else"}})
    error = _refused(run_start(*dirs, str(CHECK_MODEL)), check=stand_in.check)
    assert error["code"] == "runner.requirement-unmet"
    assert error["details"]["found"] == "something else"


def test_off_macos_the_platform_check_loads_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    import mistralrs

    from troupe_runner_mistralrs import engine

    def no_load(*args: object, **kwargs: object) -> None:
        raise AssertionError("the check loaded a model")

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(mistralrs, "Runner", no_load)
    engine.check_platform()
    monkeypatch.setattr(sys, "platform", "win32")
    engine.check_platform()


def test_an_acknowledged_run_is_answered_before_its_model_loads(dirs: tuple[Path, Path]) -> None:
    # The loader looks at what the runner has written when it's called: the run/start answer must
    # already be there (design D4). The worker sends nothing more once input ends, so the loader
    # holds the main thread's end of input back until it has looked.
    stdout = io.BytesIO()
    looked = threading.Event()
    seen: list[bytes] = []
    stand_in = StandIn({})

    def loader(spec: LoadSpec) -> Any:  # noqa: ANN401
        seen.append(stdout.getvalue())
        looked.set()
        return stand_in.load(spec)

    class HeldInput(io.BytesIO):
        def readline(self, size: int | None = -1) -> bytes:
            line = super().readline(size)
            if not line:
                looked.wait(10)
            return line

    lines = [initialize(), start_message(run_start(*dirs, str(CHECK_MODEL)))]
    stdin = HeldInput(b"".join(json.dumps(line).encode() + b"\n" for line in lines))
    Runner(stdin, stdout, io.BytesIO(), loader=loader, check=stand_in.check).run()
    (written,) = seen
    answers = [json.loads(line) for line in written.splitlines()]
    assert any(a.get("id") == 2 and "result" in a for a in answers)  # answered, then loaded
