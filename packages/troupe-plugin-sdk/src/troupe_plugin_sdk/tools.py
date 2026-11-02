"""Running a model's tool calls in a workspace (spec: runner-tools; runner-sdk design D5, D8, D9).

A runner whose engine returns tool calls rather than doing them itself gives each call to
``Tools.run``. It checks the call, checks every path against the workspace and the actor's declared
effects, carries it out, and returns what happened: the ``tool_call`` and ``tool_result`` events to
send, and the text to give the model. Nothing a model can get wrong ends the run: an unknown tool,
malformed input, a refused path or effect, or a call that fails is an error result saying why.

The tools are file tools only: ``Read``, ``Write``, ``Edit``, ``Glob`` and ``Grep``, named as
Claude Code names them, and troupe's own ``Delete`` and ``Move``. There's no shell (#239).

::

    tools = Tools(workspace, effects, limits=ToolLimits())
    tools.definitions()   # each tool's name, description and input schema, for the model
    step = tools.run(call_id, name, arguments, numbering)
    step.events           # (ToolCallEvent, ToolResultEvent): send them
    step.output           # give this to the model

The SDK sends nothing and does no I/O except on the workspace.
"""

import json
import os
import re
import stat
import tempfile
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from troupe_plugin_sdk.defaults import ToolLimits
from troupe_plugin_sdk.effects import READ_ONLY, Effect, Effects, PatternError, pattern_regex
from troupe_plugin_sdk.events import EventNumbering, fit, utf8_size
from troupe_plugin_sdk.paths import GIT, PathRefusedError, Workspace, WorkspacePath
from troupe_plugin_sdk.runner import ToolCallEvent, ToolResultEvent

# Each tool's input: its fields, their types, and whether they're required. The input schemas the
# model sees and the checks a call goes through are both made from this, so they can't disagree.

FieldType = Literal["string", "integer", "boolean"]


@dataclass(frozen=True)
class Field:
    name: str
    type: FieldType
    description: str
    required: bool = True
    minimum: int | None = None


@dataclass(frozen=True)
class ToolDefinition:
    """What a runner tells its model about a tool."""

    name: str
    description: str
    input_schema: dict[str, Any]


_TOOLS: dict[str, tuple[str, tuple[Field, ...]]] = {
    "Read": (
        "Read a text file in the workspace. Returns its lines, each with its line number. Use "
        "offset and limit to read part of a large file.",
        (
            Field("file_path", "string", "The file, relative to the workspace, such as src/a.py."),
            Field("offset", "integer", "The first line to read, from 1.", False, 1),
            Field("limit", "integer", "How many lines to read.", False, 1),
        ),
    ),
    "Write": (
        "Create a file, or replace a whole file, with the content given. Missing directories are "
        "made. To change part of a file, use Edit.",
        (
            Field("file_path", "string", "The file, relative to the workspace."),
            Field("content", "string", "The whole of the file's new content."),
        ),
    ),
    "Edit": (
        "Replace old_string with new_string in a file. old_string must occur exactly once, unless "
        "replace_all is true.",
        (
            Field("file_path", "string", "The file, relative to the workspace."),
            Field("old_string", "string", "The exact text to replace."),
            Field("new_string", "string", "The text to put in its place."),
            Field("replace_all", "boolean", "Replace every occurrence.", False),
        ),
    ),
    "Glob": (
        "List the files whose paths match a pattern: * matches within one part of a path, ? one "
        "character, and ** any number of parts, as in src/**/*.py.",
        (
            Field("pattern", "string", "The pattern, relative to path."),
            Field("path", "string", "The directory to search, relative to the workspace.", False),
        ),
    ),
    "Grep": (
        "Search files for lines matching a regular expression (Python's syntax). Returns each "
        "match as path:line:text.",
        (
            Field("pattern", "string", "The regular expression."),
            Field(
                "path", "string", "A file or directory to search, relative to the workspace.", False
            ),
            Field("glob", "string", "Only search files whose paths match this pattern.", False),
        ),
    ),
    "Delete": (
        "Delete one file.",
        (Field("file_path", "string", "The file, relative to the workspace."),),
    ),
    "Move": (
        "Move or rename one file. The destination must not exist yet; missing directories are "
        "made.",
        (
            Field("source", "string", "The file to move, relative to the workspace."),
            Field("destination", "string", "Where it goes, relative to the workspace."),
        ),
    ),
}

NAMES: tuple[str, ...] = tuple(_TOOLS)
"""The tools, in the order they're offered."""


def _schema(fields: tuple[Field, ...]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for field in fields:
        prop: dict[str, Any] = {"type": field.type, "description": field.description}
        if field.minimum is not None:
            prop["minimum"] = field.minimum
        properties[field.name] = prop
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [field.name for field in fields if field.required],
        "properties": properties,
    }


class _CallError(Exception):
    """A call that can't be carried out, with the text the model gets."""

    def __init__(self, output: str) -> None:
        super().__init__(output)
        self.output = output


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key, value in pairs:
        if key in data:
            raise _CallError(f"The input has the field {key!r} twice.")
        data[key] = value
    return data


def _no_constant(constant: str) -> Any:  # noqa: ANN401 - json's parse_constant hook
    raise _CallError(f"The input has {constant}, which isn't a JSON number.")


def _check_input(name: str, fields: tuple[Field, ...], raw: object) -> dict[str, Any]:
    """The call's input as an object that fits the tool's fields, or a _CallError naming the
    problem and the field."""
    data: object = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw, object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
        except json.JSONDecodeError as error:
            raise _CallError(f"{name}'s input isn't valid JSON: {error.msg}.") from error
    if not isinstance(data, Mapping):
        raise _CallError(f"{name}'s input must be a JSON object.")
    known = {field.name: field for field in fields}
    unknown = sorted(str(key) for key in data if key not in known)
    if unknown:
        listed = ", ".join(known)
        raise _CallError(f"{name} doesn't take {', '.join(unknown)}. It takes {listed}.")
    for field in fields:
        if field.name not in data:
            if field.required:
                raise _CallError(f"{name} needs {field.name}.")
            continue
        value = data[field.name]
        if field.type == "string":
            ok = isinstance(value, str)
        elif field.type == "boolean":
            ok = isinstance(value, bool)
        else:
            ok = isinstance(value, int) and not isinstance(value, bool)
            if ok and field.minimum is not None and value < field.minimum:
                raise _CallError(f"{name}'s {field.name} must be at least {field.minimum}.")
        if not ok:
            article = "an" if field.type == "integer" else "a"
            raise _CallError(f"{name}'s {field.name} must be {article} {field.type}.")
    return dict(data)


def _summary(raw: Mapping[str, object] | str) -> str:
    if isinstance(raw, str):
        return raw
    try:
        return json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(raw)


@dataclass(frozen=True)
class ToolStep:
    """One call, carried out or refused: its events and the text for the model."""

    call: ToolCallEvent
    result: ToolResultEvent
    output: str
    is_error: bool

    @property
    def events(self) -> tuple[ToolCallEvent, ToolResultEvent]:
        return (self.call, self.result)


def _lines(text: str) -> list[str]:
    """``text``'s lines without their endings (``\\n`` or ``\\r\\n``)."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line.removesuffix("\r") for line in lines]


def _decode(data: bytes, shown: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _CallError(f"{shown} isn't a text file (it isn't valid UTF-8).") from error


def _write_atomically(target: Path, data: bytes) -> None:
    """Write ``data`` to ``target`` without ever leaving it half written: to a temporary file
    beside it, then replace. An existing file's mode is kept. Bytes, so no newline is
    translated."""
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=".troupe-write-")
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _is_link(path: Path) -> bool:
    """Whether ``path`` is a symbolic link or a Windows junction."""
    return path.is_symlink() or os.path.isjunction(path)


class Tools:
    """The seven tools, for one workspace and one actor's declared effects."""

    def __init__(
        self, workspace: Path, effects: Effects = READ_ONLY, limits: ToolLimits | None = None
    ) -> None:
        self.workspace = Workspace(workspace)
        self.effects = effects
        self.limits = limits if limits is not None else ToolLimits()
        self._run: dict[str, Callable[[dict[str, Any]], str]] = {
            "Read": self._read,
            "Write": self._write,
            "Edit": self._edit,
            "Glob": self._glob,
            "Grep": self._grep,
            "Delete": self._delete,
            "Move": self._move,
        }

    @staticmethod
    def definitions() -> tuple[ToolDefinition, ...]:
        """Each tool's name, description and closed input schema, to offer the model."""
        return tuple(
            ToolDefinition(name, description, _schema(fields))
            for name, (description, fields) in _TOOLS.items()
        )

    @staticmethod
    def names() -> list[str]:
        """The tools' names, for the init event's ``tools``."""
        return list(NAMES)

    def run(
        self,
        call_id: str,
        name: str,
        arguments: Mapping[str, object] | str,
        numbering: EventNumbering,
    ) -> ToolStep:
        """Check and carry out one call, and number its two events. ``arguments`` is the input as
        an object, or as the JSON text of one. An empty ``call_id`` is the runner's mistake, so
        it's a ValueError; everything else is the result."""
        if not call_id:
            raise ValueError(
                "a tool call needs a non-empty call id; make one up if the engine gave none"
            )
        try:
            if name not in _TOOLS:
                raise _CallError(
                    f"There's no tool named {name!r}. The tools are {', '.join(NAMES)}."
                )
            data = _check_input(name, _TOOLS[name][1], arguments)
            output, is_error = self._run[name](data), False
        except _CallError as error:
            output, is_error = error.output, True
        except PathRefusedError as error:
            output, is_error = error.problem, True
        call = fit(
            {
                "runId": numbering.run_id,
                "seq": numbering.take(),
                "type": "tool_call",
                "callId": call_id,
                "tool": name or "(no name)",
                "inputSummary": _summary(arguments),
            },
            "inputSummary",
            min(numbering.summary_max_bytes, self.limits.summary_max_bytes),
            numbering.event_max_bytes,
        )
        result = fit(
            {
                "runId": numbering.run_id,
                "seq": numbering.take(),
                "type": "tool_result",
                "callId": call_id,
                "isError": is_error,
                "outputSummary": output,
                "outputBytes": utf8_size(output),
            },
            "outputSummary",
            min(numbering.summary_max_bytes, self.limits.summary_max_bytes),
            numbering.event_max_bytes,
        )
        return ToolStep(
            ToolCallEvent.from_data(call), ToolResultEvent.from_data(result), output, is_error
        )

    # Checks shared by the tools

    def _allowed(self, tool: str, effect: Effect, path: WorkspacePath) -> None:
        if self.effects.allows(effect, path.relative):
            return
        declared = self.effects.declared(effect)
        has = (
            f"It declares {effect} for: {', '.join(declared)}."
            if declared
            else f"It declares no {effect} paths."
        )
        raise _CallError(
            f"{tool} on {path.relative} needs the {effect} effect for {path.relative}, which this "
            f"actor doesn't declare. {has}"
        )

    def _file(self, path: WorkspacePath, load: str | None = None) -> None:
        """Refuse a path that isn't an existing regular file. With ``load``, the tool that reads
        it whole, refuse one over the file limit too, before anything reads it."""
        try:
            status = path.absolute.stat()
        except FileNotFoundError:
            raise _CallError(f"{path.relative} doesn't exist.") from None
        except OSError as error:
            raise self._failed(load or "The call", path, error) from error
        if stat.S_ISDIR(status.st_mode):
            raise _CallError(f"{path.relative} is a directory, not a file.")
        if not stat.S_ISREG(status.st_mode):
            raise _CallError(
                f"{path.relative} isn't a regular file, so it can't be read or changed."
            )
        cap = self.limits.file_max_bytes
        if load is not None and status.st_size > cap:
            raise _CallError(
                f"{path.relative} is {status.st_size} bytes, over the {cap}-byte limit for {load}."
            )

    def _failed(self, tool: str, path: WorkspacePath, error: OSError) -> _CallError:
        # strerror, never str(error): the full message names the host path.
        reason = error.strerror or type(error).__name__
        return _CallError(f"{tool} on {path.relative} failed: {reason}.")

    # The tools

    def _read(self, data: dict[str, Any]) -> str:
        path = self.workspace.path(data["file_path"])
        self._file(path, load="Read")
        offset: int = data.get("offset", 1)
        wanted: int = min(data.get("limit", self.limits.read_max_lines), self.limits.read_max_lines)
        try:
            raw = path.absolute.read_bytes()
        except OSError as error:
            raise self._failed("Read", path, error) from error
        lines = _lines(_decode(raw, path.relative))
        if not lines:
            return f"{path.relative} is empty."
        if offset > len(lines):
            raise _CallError(
                f"{path.relative} has {len(lines)} lines, so offset {offset} is past its end."
            )
        last = min(len(lines), offset - 1 + wanted)
        cap = self.limits.read_max_bytes
        out: list[str] = []
        size = 0
        number = offset
        while number <= last:
            line = f"{number}\t{lines[number - 1]}"
            if size + utf8_size(line) + 1 > cap:
                if not out:
                    out.append(line.encode("utf-8")[:cap].decode("utf-8", errors="ignore"))
                    out.append(
                        f"[Line {number} is longer than {cap} bytes; only its start is shown.]"
                    )
                    number += 1
                break
            out.append(line)
            size += utf8_size(line) + 1
            number += 1
        if number <= len(lines):
            out.append(
                f"[Stopped before line {number} of {len(lines)}: read on with offset {number}.]"
            )
        return "\n".join(out)

    def _write(self, data: dict[str, Any]) -> str:
        path = self.workspace.path(data["file_path"])
        self._allowed("Write", "write", path)
        if path.absolute.is_dir():
            raise _CallError(f"{path.relative} is a directory, not a file.")
        content: str = data["content"]
        encoded = content.encode("utf-8")
        try:
            _write_atomically(path.absolute, encoded)
        except OSError as error:
            raise self._failed("Write", path, error) from error
        return f"Wrote {len(encoded)} bytes to {path.relative}."

    def _edit(self, data: dict[str, Any]) -> str:
        path = self.workspace.path(data["file_path"])
        self._allowed("Edit", "write", path)
        self._file(path, load="Edit")
        old: str = data["old_string"]
        new: str = data["new_string"]
        if not old:
            raise _CallError("Edit's old_string is empty. Give the exact text to replace.")
        if old == new:
            raise _CallError(
                "Edit's old_string and new_string are the same, so nothing would change."
            )
        try:
            text = _decode(path.absolute.read_bytes(), path.relative)
        except OSError as error:
            raise self._failed("Edit", path, error) from error
        count = text.count(old)
        if count == 0:
            raise _CallError(
                f"old_string isn't in {path.relative}. Read the file to find the exact text."
            )
        if count > 1 and not data.get("replace_all", False):
            raise _CallError(
                f"old_string occurs {count} times in {path.relative}. Give more context so it "
                "occurs once, or set replace_all."
            )
        try:
            _write_atomically(path.absolute, text.replace(old, new).encode("utf-8"))
        except OSError as error:
            raise self._failed("Edit", path, error) from error
        return f"Replaced {count} occurrence{'s' if count > 1 else ''} in {path.relative}."

    def _files(self, start: WorkspacePath) -> Iterator[str]:
        """Every file under ``start``, workspace-relative, sorted, without following links out of
        the workspace or into ``.git``.

        It never descends into a directory link: ``os.walk(followlinks=False)`` skips symbolic
        links but descends into a Windows junction, which isn't one, so each directory is checked
        with ``os.path.isjunction`` as well (runner-sdk design D9)."""
        root = self.workspace.root
        found: list[str] = []
        for directory, dirnames, filenames in os.walk(start.absolute, followlinks=False):
            here = Path(directory)
            relative = PurePosixPath(*here.relative_to(root).parts)
            if not relative.parts:
                dirnames[:] = [d for d in dirnames if d.casefold() != GIT]
                filenames = [f for f in filenames if f.casefold() != GIT]
            dirnames[:] = sorted(d for d in dirnames if not _is_link(here / d))
            for name in filenames:
                file = here / name
                if file.is_symlink() and not self.workspace.contains(file):
                    continue
                found.append((relative / name).as_posix())
        yield from sorted(found)

    def _start(self, data: dict[str, Any]) -> WorkspacePath:
        start = self.workspace.path(data.get("path", "."), directory=True)
        if not start.absolute.exists():
            raise _CallError(f"{start.relative or '.'} doesn't exist.")
        return start

    def _matcher(self, pattern: str, field: str) -> re.Pattern[str]:
        try:
            return pattern_regex(pattern, field)
        except PatternError as error:
            raise _CallError(f"The {error}.") from error

    def _under(self, start: WorkspacePath, file: str) -> str:
        """``file`` relative to ``start``, for matching a pattern given relative to it."""
        return file[len(start.relative) + 1 :] if start.relative else file

    def _glob(self, data: dict[str, Any]) -> str:
        matcher = self._matcher(data["pattern"], "pattern")
        start = self._start(data)
        if not start.absolute.is_dir():
            raise _CallError(f"{start.relative} is a file; Glob's path is a directory.")
        matched = [f for f in self._files(start) if matcher.match(self._under(start, f))]
        if not matched:
            return "No files match."
        cap = self.limits.glob_max_paths
        shown = matched[:cap]
        if len(matched) > cap:
            shown.append(
                f"[{len(matched) - cap} more paths not shown: narrow the pattern or the path.]"
            )
        return "\n".join(shown)

    def _grep(self, data: dict[str, Any]) -> str:
        try:
            expression = re.compile(data["pattern"])
        except re.error as error:
            raise _CallError(
                f"The pattern {data['pattern']!r} isn't a valid regular expression: {error}."
            ) from error
        only = self._matcher(data["glob"], "glob") if "glob" in data else None
        start = self._start(data)
        if start.absolute.is_dir():
            files = [
                f for f in self._files(start) if only is None or only.match(self._under(start, f))
            ]
        else:
            files = [start.relative]
        cap = self.limits.grep_max_matches
        matches: list[str] = []
        more = 0
        too_large = not_text = special = 0
        root = self.workspace.root
        for file in files:
            absolute = root.joinpath(*file.split("/"))
            if not self.workspace.contains(absolute):
                continue  # never read outside the workspace, whatever the walk found
            try:
                status = absolute.stat()
                if not stat.S_ISREG(status.st_mode):
                    special += 1
                    continue
                if status.st_size > self.limits.grep_file_max_bytes:
                    too_large += 1
                    continue
                text = absolute.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                not_text += 1
                continue
            except OSError:
                not_text += 1
                continue
            for number, line in enumerate(_lines(text), start=1):
                if expression.search(line):
                    if len(matches) < cap:
                        matches.append(f"{file}:{number}:{line}")
                    else:
                        more += 1
        out = matches or ["No matches."]
        if more:
            out.append(f"[{more} more matches not shown: narrow the pattern, path or glob.]")
        if too_large:
            limit = self.limits.grep_file_max_bytes
            out.append(f"[{too_large} files over {limit} bytes were skipped.]")
        if not_text:
            out.append(f"[{not_text} files that aren't UTF-8 text were skipped.]")
        if special:
            out.append(f"[{special} entries that aren't regular files were skipped.]")
        return "\n".join(out)

    def _delete(self, data: dict[str, Any]) -> str:
        path = self.workspace.path(data["file_path"])
        self._allowed("Delete", "delete", path)
        if path.absolute.is_dir():
            raise _CallError(f"{path.relative} is a directory. Only files can be deleted.")
        if not path.absolute.exists():
            raise _CallError(f"{path.relative} doesn't exist.")
        try:
            path.absolute.unlink()
        except OSError as error:
            raise self._failed("Delete", path, error) from error
        return f"Deleted {path.relative}."

    def _move(self, data: dict[str, Any]) -> str:
        source = self.workspace.path(data["source"])
        destination = self.workspace.path(data["destination"])
        self._allowed("Move", "move", source)
        self._allowed("Move", "move", destination)
        self._file(source)
        if os.path.lexists(destination.absolute):
            raise _CallError(f"{destination.relative} already exists. Move doesn't replace a file.")
        try:
            destination.absolute.parent.mkdir(parents=True, exist_ok=True)
            os.rename(source.absolute, destination.absolute)
        except OSError as error:
            raise self._failed("Move", source, error) from error
        return f"Moved {source.relative} to {destination.relative}."
