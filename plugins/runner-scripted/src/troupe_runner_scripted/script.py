"""Scripts and recordings: reading them strictly (design D12, D14; spec: scripted-runner).

A script is ``{"onCancel": ..., "steps": [...]}``. Each step is an object with exactly one key, the
step's kind. A recording is JSON Lines, each line ``{"event": {...}}`` or ``{"transcript": "..."}``,
optionally with ``atMs``. Anything unknown is refused with an error naming it, never ignored.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

from troupe_plugin_sdk import runner as p

OnCancel = Literal["honour", "honour-with-result", "ignore"]
ON_CANCEL: tuple[OnCancel, ...] = ("honour", "honour-with-result", "ignore")

OPTION_KEYS = frozenset({"script", "scriptPath", "replayDelays"})


class ScriptError(ValueError):
    """A script, recording or option the runner refuses, with what was wrong and where."""

    def __init__(self, code: str, problem: str, where: str) -> None:
        super().__init__(f"{where}: {problem}")
        self.code = code
        self.problem = problem
        self.where = where


@dataclass(frozen=True)
class Step:
    kind: str
    value: Any


@dataclass(frozen=True)
class Script:
    on_cancel: OnCancel
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class Options:
    script: Script
    replay_delays: bool
    base: Path
    """Where relative replay paths are found: the script file's directory, or the workspace."""


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key, value in pairs:
        if key in data:
            raise ScriptError("scripted.invalid-script", f"the key {key!r} appears twice", "JSON")
        data[key] = value
    return data


def _no_constant(constant: str) -> Any:  # noqa: ANN401 - json's parse_constant hook
    raise ScriptError("scripted.invalid-script", f"{constant} isn't a JSON number", "JSON")


def loads_strict(text: str | bytes, where: str) -> Any:  # noqa: ANN401 - any JSON value
    try:
        return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except json.JSONDecodeError as error:
        raise ScriptError("scripted.invalid-script", f"not JSON ({error})", where) from error
    except ScriptError as error:
        raise ScriptError(error.code, error.problem, where) from error


def _invalid(problem: str, where: str) -> ScriptError:
    return ScriptError("scripted.invalid-script", problem, where)


def _require_keys(data: Any, where: str, required: set[str], optional: set[str]) -> None:  # noqa: ANN401
    if not isinstance(data, dict):
        raise _invalid("must be an object", where)
    unknown = sorted(set(data) - required - optional)
    if unknown:
        raise _invalid(f"unknown field(s) {', '.join(map(repr, unknown))}", where)
    missing = sorted(required - set(data))
    if missing:
        raise _invalid(f"missing field(s) {', '.join(map(repr, missing))}", where)


def _int(value: Any, where: str, minimum: int | None = None) -> int:  # noqa: ANN401
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid("must be an integer", where)
    if minimum is not None and value < minimum:
        raise _invalid(f"must be at least {minimum}", where)
    return value


def _str(value: Any, where: str) -> str:  # noqa: ANN401
    if not isinstance(value, str):
        raise _invalid("must be a string", where)
    return value


def workspace_relative(path: str, where: str) -> PurePosixPath:
    """A path that stays inside the workspace: relative, no drive, no root, no ``..``."""
    windows, posix = PureWindowsPath(path), PurePosixPath(path)
    if not path or windows.drive or windows.root or posix.is_absolute():
        raise _invalid(f"{path!r} must be a relative path inside the workspace", where)
    parts = PurePosixPath(*windows.parts).parts
    if ".." in parts:
        raise _invalid(f"{path!r} must not leave the workspace with '..'", where)
    return PurePosixPath(*parts)


_PLACEHOLDER_RUN_ID = "00000000-0000-4000-8000-000000000000"


def _event_shape(value: dict[str, Any], where: str) -> None:
    """Check an event step against the plugin SDK's type for its event (runner-sdk design D4). The
    runner fills in runId and seq when it plays the step, so they're filled in here only to check
    the rest; a step that gives them keeps its own, which is how a script breaks the contract's
    sequence on purpose."""
    seq = 0 if value["type"] == "init" else 1
    filled: dict[str, Any] = {"runId": _PLACEHOLDER_RUN_ID, "seq": seq}
    if value["type"] == "init":
        filled["effects"] = "checked"
    try:
        p.parse_event({**filled, **value})
    except p.ProtocolError as error:
        raise _invalid(str(error), where) from error


CHECK_CHARACTER = 'a checkCharacter step is {"hash": "sha256:..."} or {"absent": true}'


CHECK_RUNTIME = (
    'a checkRuntime step is {"absent": true}, or any of name, endpoint, model (strings) and '
    'credentialHash ("sha256:...") or noCredential (true)'
)


def _check_runtime_step(value: Any, here: str) -> None:  # noqa: ANN401
    if not isinstance(value, dict):
        raise _invalid(CHECK_RUNTIME, here)
    if "absent" in value:
        if value != {"absent": True}:
            raise _invalid(CHECK_RUNTIME, here)
        return
    _require_keys(
        value, here, set(), {"name", "endpoint", "model", "credentialHash", "noCredential"}
    )
    if not value or ("credentialHash" in value and "noCredential" in value):
        raise _invalid(CHECK_RUNTIME, here)
    for field in ("name", "endpoint", "model"):
        if field in value:
            _str(value[field], f"{here}.{field}")
    if "noCredential" in value and value["noCredential"] is not True:
        raise _invalid("must be true", f"{here}.noCredential")
    if "credentialHash" in value:
        hash_ = _str(value["credentialHash"], f"{here}.credentialHash")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", hash_):
            raise _invalid("must be sha256: and 64 lowercase hex digits", f"{here}.credentialHash")


def _step(data: Any, where: str) -> Step:  # noqa: ANN401
    if not isinstance(data, dict) or len(data) != 1:
        raise _invalid("a step is an object with exactly one key, the step's kind", where)
    ((kind, value),) = data.items()
    here = f"{where}.{kind}"
    if kind == "event":
        if not isinstance(value, dict) or not isinstance(value.get("type"), str):
            raise _invalid("an event step is an object with a type", here)
        _event_shape(value, here)
    elif kind == "transcript":
        if isinstance(value, dict):
            _require_keys(value, here, {"record"}, {"encoding"})
            _str(value["record"], f"{here}.record")
            if value.get("encoding", "utf-8") not in ("utf-8", "base64"):
                raise _invalid("encoding must be 'utf-8' or 'base64'", f"{here}.encoding")
        else:
            _str(value, here)
    elif kind in ("stderr", "rawStdout", "replay"):
        _str(value, here)
    elif kind == "wait":
        _require_keys(value, here, {"ms"}, set())
        _int(value["ms"], f"{here}.ms", minimum=0)
    elif kind == "writeFile":
        _require_keys(value, here, {"path", "content"}, set())
        workspace_relative(_str(value["path"], f"{here}.path"), f"{here}.path")
        _str(value["content"], f"{here}.content")
    elif kind == "hang":
        if value is not True:
            raise _invalid('a hang step is {"hang": true}', here)
    elif kind == "exit":
        _int(value, here, minimum=0)
    elif kind == "checkCharacter":
        if not isinstance(value, dict) or len(value) != 1:
            raise _invalid(
                'a checkCharacter step is {"hash": "sha256:..."} or {"absent": true}', here
            )
        if "hash" in value:
            hash_ = _str(value["hash"], f"{here}.hash")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", hash_):
                raise _invalid("must be sha256: and 64 lowercase hex digits", f"{here}.hash")
        elif value.get("absent") is not True:
            raise _invalid(
                'a checkCharacter step is {"hash": "sha256:..."} or {"absent": true}', here
            )
    elif kind == "checkRuntime":
        _check_runtime_step(value, here)
    elif kind == "echoCredential":
        if value is not True:
            raise _invalid('an echoCredential step is {"echoCredential": true}', here)
    elif kind == "tool":
        _require_keys(value, here, {"name", "input"}, {"callId", "isError"})
        if not _str(value["name"], f"{here}.name"):
            raise _invalid("must not be empty", f"{here}.name")
        given = value["input"]
        if not isinstance(given, dict | str):
            raise _invalid("must be an object, or the JSON text of one", f"{here}.input")
        if isinstance(given, dict):
            for field, inner in given.items():
                if not isinstance(inner, str | int):  # a bool is an int
                    raise _invalid(
                        "must be a string, a whole number or a boolean", f"{here}.input.{field}"
                    )
        if "callId" in value and not _str(value["callId"], f"{here}.callId"):
            raise _invalid("must not be empty", f"{here}.callId")
        if "isError" in value and not isinstance(value["isError"], bool):
            raise _invalid("must be true or false", f"{here}.isError")
    else:
        raise _invalid(f"unknown step {kind!r}", where)
    return Step(kind, value)


def parse_script(data: Any, where: str = "script") -> Script:  # noqa: ANN401
    _require_keys(data, where, {"steps"}, {"onCancel"})
    on_cancel = data.get("onCancel", "honour")
    if on_cancel not in ON_CANCEL:
        raise _invalid(f"must be one of {', '.join(ON_CANCEL)}", f"{where}.onCancel")
    steps = data["steps"]
    if not isinstance(steps, list):
        raise _invalid("must be an array", f"{where}.steps")
    return Script(on_cancel, tuple(_step(s, f"{where}.steps[{i}]") for i, s in enumerate(steps)))


def parse_options(options: Any, workspace: Path) -> Options:  # noqa: ANN401
    if not isinstance(options, dict):
        raise _invalid("options must be an object", "options")
    unknown = sorted(set(options) - OPTION_KEYS)
    if unknown:
        raise ScriptError(
            "scripted.unknown-option",
            f"unknown option(s) {', '.join(map(repr, unknown))}; the scripted runner takes "
            f"{', '.join(sorted(OPTION_KEYS))}",
            "options",
        )
    if ("script" in options) == ("scriptPath" in options):
        raise _invalid("give exactly one of script and scriptPath", "options")
    replay_delays = options.get("replayDelays", False)
    if not isinstance(replay_delays, bool):
        raise _invalid("must be true or false", "options.replayDelays")
    if "script" in options:
        return Options(parse_script(options["script"]), replay_delays, workspace)
    path = Path(_str(options["scriptPath"], "options.scriptPath"))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise _invalid(
            f"can't read {path}: {error.strerror or error}", "options.scriptPath"
        ) from error
    script = parse_script(loads_strict(text, str(path)), str(path))
    return Options(script, replay_delays, path.parent)


@dataclass(frozen=True)
class Record:
    """One recorded message: an event or a transcript record, and when it was sent."""

    event: dict[str, Any] | None
    transcript: str | None
    at_ms: int | None


def read_recording(path: Path) -> list[Record]:
    try:
        lines = path.read_bytes().splitlines()
    except OSError as error:
        raise _invalid(f"can't read {path}: {error.strerror or error}", "replay") from error
    records = []
    for number, line in enumerate(lines, start=1):
        where = f"{path.name}:{number}"
        data = loads_strict(line, where)
        if not isinstance(data, dict) or len(set(data) & {"event", "transcript"}) != 1:
            raise _invalid("each line holds exactly one of event and transcript", where)
        _require_keys(data, where, set(), {"event", "transcript", "atMs"})
        at_ms = _int(data["atMs"], f"{where}.atMs", minimum=0) if "atMs" in data else None
        if "event" in data:
            if not isinstance(data["event"], dict):
                raise _invalid("an event must be an object", f"{where}.event")
            records.append(Record(data["event"], None, at_ms))
        else:
            records.append(Record(None, _str(data["transcript"], f"{where}.transcript"), at_ms))
    return records
