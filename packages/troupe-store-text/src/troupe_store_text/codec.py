"""One line of an event segment (spec: event-store; design D3; event-record.schema.json).

A segment starts with a header line, followed by one line per event. Lines are strict JSON. An
event's id is the SHA-256 of what it changed: its stream, version, topic, parents and state, with
the state's ``timestamp`` and ``lineage`` left out, so two clones that make the same change agree on
the id whoever made it, wherever and whenever.

State is written inline as JSON when its bytes are canonical JSON (troupe's own events always are);
otherwise its bytes are written as base64, so every payload reads back byte for byte.
"""

import base64
import binascii
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from troupe.core import strict_json
from troupe.core.errors import TroupeError

FORMAT = 1
HASH_PREFIX = "sha256:"
_HASH_LENGTH = len(HASH_PREFIX) + 64
LEFT_OUT_OF_THE_HASH = ("timestamp", "lineage")
"""Top-level state keys the content hash ignores: when it happened and who did it."""


@dataclass(frozen=True)
class Header:
    """A segment's first line: who wrote it, and on which branch (None, and left out of the line,
    for a segment written with no branch)."""

    session: str
    vcs: str
    branch: str | None


@dataclass(frozen=True)
class Record:
    """One recorded event, and where its line is."""

    id: str
    stream: UUID | str
    version: int
    topic: str
    parents: tuple[str, ...]
    state: bytes
    batch_id: str
    batch_index: int
    batch_size: int
    path: Path
    line: int

    @property
    def lineage(self) -> dict[str, Any] | None:
        """The lineage in this event's state, if the state is a JSON object that has one."""
        try:
            data = strict_json.loads(self.state)
        except strict_json.StrictJSONError:
            return None
        if isinstance(data, dict) and isinstance(data.get("lineage"), dict):
            lineage: dict[str, Any] = data["lineage"]
            return lineage
        return None


def stream_fields(stream: UUID | str) -> tuple[str, str]:
    if isinstance(stream, UUID):
        return str(stream), "uuid"
    return stream, "str"


def _inline(state: bytes) -> dict[str, Any] | None:
    """The state as a JSON object, if its bytes are exactly that object's canonical form."""
    try:
        data = strict_json.loads(state)
    except strict_json.StrictJSONError:
        return None
    if not isinstance(data, dict) or strict_json.dumps(data).encode("utf-8") != state:
        return None
    return data


def content_id(
    stream: UUID | str, version: int, topic: str, parents: tuple[str, ...], state: bytes
) -> str:
    """The event's id: the SHA-256 of what it changed, leaving out when and by whom."""
    text, kind = stream_fields(stream)
    inline = _inline(state)
    content: object
    if inline is None:
        content = base64.b64encode(state).decode("ascii")
    else:
        content = {key: value for key, value in inline.items() if key not in LEFT_OUT_OF_THE_HASH}
    canonical = strict_json.dumps(
        {
            "stream": text,
            "stream_type": kind,
            "version": version,
            "topic": topic,
            "parents": sorted(parents),
            "state": content,
        }
    )
    return HASH_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def encode_header(header: Header) -> bytes:
    segment = {"session": header.session, "vcs": header.vcs}
    if header.branch is not None:
        segment["branch"] = header.branch
    line = {"format": FORMAT, "segment": segment}
    return strict_json.dumps(line).encode("utf-8") + b"\n"


def encode_event(
    stream: UUID | str,
    version: int,
    topic: str,
    parents: tuple[str, ...],
    state: bytes,
    batch: tuple[str, int, int],
) -> tuple[str, bytes]:
    """The event's id and its line."""
    event_id = content_id(stream, version, topic, parents, state)
    text, kind = stream_fields(stream)
    line: dict[str, Any] = {
        "format": FORMAT,
        "id": event_id,
        "stream": text,
        "stream_type": kind,
        "version": version,
        "topic": topic,
        "parents": list(parents),
        "batch": {"id": batch[0], "index": batch[1], "size": batch[2]},
    }
    inline = _inline(state)
    if inline is None:
        line["state_b64"] = base64.b64encode(state).decode("ascii")
    else:
        line["state"] = inline
    return event_id, strict_json.dumps(line).encode("utf-8") + b"\n"


def decode(raw: bytes, path: Path, line: int) -> Header | Record:
    """Read one complete line, strictly. Anything malformed is events.malformed-record."""
    text = raw.removesuffix(b"\n").removesuffix(b"\r")
    try:
        data = strict_json.loads(text)
    except strict_json.StrictJSONError as error:
        raise malformed(path, line, str(error)) from error
    if not isinstance(data, dict):
        raise malformed(path, line, "a line must be a JSON object")
    if data.get("format") != FORMAT:
        raise TroupeError(
            "events.unknown-format",
            problem=f"Line {line} has record format {data.get('format')!r}; this troupe reads "
            f"format {FORMAT}.",
            fix="Upgrade troupe to a version that reads this format.",
            path=str(path.absolute()),
            details={"line": line, "format": strict_json.dumps(data.get("format"))},
        )
    if set(data) == {"format", "segment"}:
        return _header(data["segment"], path, line)
    return _record(data, path, line)


def _header(segment: object, path: Path, line: int) -> Header:
    if not isinstance(segment, dict) or set(segment) not in (
        {"session", "vcs"},
        {"session", "vcs", "branch"},
    ):
        raise malformed(
            path, line, "a header's segment must have session and vcs, and may have branch"
        )
    session, vcs = segment["session"], segment["vcs"]
    if not (isinstance(session, str) and isinstance(vcs, str) and session and vcs):
        raise malformed(path, line, "a header's session and vcs must be non-empty strings")
    branch = segment.get("branch")
    if "branch" in segment and not (isinstance(branch, str) and branch):
        raise malformed(
            path,
            line,
            "a header's branch must be a non-empty string, or left out when there is none",
        )
    return Header(session=session, vcs=vcs, branch=branch)


_EVENT_KEYS = {"format", "id", "stream", "stream_type", "version", "topic", "parents", "batch"}


def _record(data: dict[str, Any], path: Path, line: int) -> Record:
    keys = set(data)
    if keys not in (_EVENT_KEYS | {"state"}, _EVENT_KEYS | {"state_b64"}):
        raise malformed(path, line, f"unexpected or missing fields: {sorted(keys ^ _EVENT_KEYS)}")
    stream_type, stream_text = data["stream_type"], data["stream"]
    if not isinstance(stream_text, str) or not stream_text:
        raise malformed(path, line, "stream must be a non-empty string")
    stream: UUID | str
    if stream_type == "uuid":
        try:
            stream = UUID(stream_text)
        except ValueError as error:
            raise malformed(path, line, "stream isn't a UUID") from error
    elif stream_type == "str":
        stream = stream_text
    else:
        raise malformed(path, line, "stream_type must be uuid or str")
    version, topic, parents = data["version"], data["topic"], data["parents"]
    if not isinstance(version, int) or isinstance(version, bool):
        raise malformed(path, line, "version must be an integer")
    if not isinstance(topic, str) or not topic:
        raise malformed(path, line, "topic must be a non-empty string")
    if not isinstance(parents, list) or not all(_is_hash(p) for p in parents):
        raise malformed(path, line, "parents must be a list of sha256: hashes")
    if len(set(parents)) != len(parents):
        raise malformed(path, line, "parents must not repeat")
    batch = data["batch"]
    if (
        not isinstance(batch, dict)
        or set(batch) != {"id", "index", "size"}
        or not isinstance(batch["id"], str)
        or not all(
            isinstance(batch[k], int) and not isinstance(batch[k], bool) for k in ("index", "size")
        )
        or not 0 <= batch["index"] < batch["size"]
    ):
        raise malformed(path, line, "batch must be {id, index, size} with 0 <= index < size")
    if "state" in data:
        if not isinstance(data["state"], dict):
            raise malformed(path, line, "state must be a JSON object")
        state = strict_json.dumps(data["state"]).encode("utf-8")
    else:
        try:
            state = base64.b64decode(data["state_b64"], validate=True)
        except (binascii.Error, TypeError) as error:
            raise malformed(path, line, "state_b64 isn't base64") from error
    event_id = data["id"]
    expected = content_id(stream, version, topic, tuple(parents), state)
    if event_id != expected:
        raise malformed(path, line, f"id {event_id!r} doesn't match the event's content")
    return Record(
        id=event_id,
        stream=stream,
        version=version,
        topic=topic,
        parents=tuple(parents),
        state=state,
        batch_id=batch["id"],
        batch_index=batch["index"],
        batch_size=batch["size"],
        path=path,
        line=line,
    )


def _is_hash(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _HASH_LENGTH
        and value.startswith(HASH_PREFIX)
        and all(c in "0123456789abcdef" for c in value[len(HASH_PREFIX) :])
    )


def malformed(path: Path, line: int, reason: str) -> TroupeError:
    return TroupeError(
        "events.malformed-record",
        problem=f"Line {line} of an event segment isn't a valid record: {reason}.",
        fix="Restore the file from version control (git checkout -- <file>, or from the commit "
        "that added it). If it was edited by hand, undo the edit.",
        path=str(path.absolute()),
        details={"line": line, "reason": reason},
    )
