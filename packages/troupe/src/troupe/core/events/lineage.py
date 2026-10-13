"""Lineage: where an event came from (spec: lineage; design D8; lineage.schema.json).

The Python types mirror the schema, and lineage_problem checks data against the same rules by hand
(jsonschema is a development dependency only); a test validates every shape built here against the
schema, so the two can't drift. A field with nothing to say is left out, never written as null
(spec: protocol; omit-nulls).
"""

import re
from collections.abc import Mapping, Set
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from troupe.core.identity import Identity

VIA = ("cli", "file", "runner", "server")
Via = Literal["cli", "file", "runner", "server"]
HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
TIME = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$")


@dataclass(frozen=True)
class Unknown:
    """An actor nobody can know, such as whoever edited a file by hand. Never a failure to
    resolve: that fails the command instead."""

    def to_data(self) -> dict[str, Any]:
        return {"kind": "unknown"}


Actor = Identity | Unknown


def actor_data(actor: Actor) -> dict[str, Any]:
    if isinstance(actor, Unknown):
        return actor.to_data()
    return {"kind": actor.kind, "id": actor.id, "source": actor.source}


@dataclass(frozen=True)
class CommandCause:
    """Recorded directly by the command whose change id this is."""

    id: str

    def to_data(self) -> dict[str, Any]:
        return {"kind": "command", "id": self.id}


@dataclass(frozen=True)
class EventCause:
    """Recorded in reaction to the event with this id."""

    id: str

    def to_data(self) -> dict[str, Any]:
        return {"kind": "event", "id": self.id}


Cause = CommandCause | EventCause


@dataclass(frozen=True)
class Source:
    """The file an event was made from: its theatre-relative path, and its content hashes before
    and after (None for a file that didn't exist, or no longer does)."""

    path: str
    before: str | None
    after: str | None


@dataclass(frozen=True)
class VcsState:
    adapter: str
    branch: str | None
    head: str | None
    source: Source | None = None

    def to_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {"adapter": self.adapter}
        if self.branch is not None:
            data["branch"] = self.branch
        if self.head is not None:
            data["head"] = self.head
        if self.source is not None:
            source = {"path": self.source.path}
            if self.source.before is not None:
                source["before"] = self.source.before
            if self.source.after is not None:
                source["after"] = self.source.after
            data["source"] = source
        return data


Effects = Literal["enforced", "unenforced"]
STAGE_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
SETTING_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class Allowance:
    """The policy setting, and the source of its value, that allowed a run whose effects a stage
    couldn't enforce (decision #3)."""

    setting: str
    source: str


@dataclass(frozen=True)
class StageLineage:
    """Where a run's actor ran, and whether troupe enforced its effects there (design D7)."""

    name: str
    effects: Effects
    allowed_by: Allowance | None

    def __post_init__(self) -> None:
        if (self.effects == "unenforced") != (self.allowed_by is not None):
            raise ValueError(
                "an unenforced stage names what allowed it, and an enforced one doesn't"
            )

    def to_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {"name": self.name, "effects": self.effects}
        if self.allowed_by is not None:
            data["allowedBy"] = {
                "setting": self.allowed_by.setting,
                "source": self.allowed_by.source,
            }
        return data


@dataclass(frozen=True)
class Approval:
    actor: Actor
    role: str
    at: str


@dataclass(frozen=True)
class Lineage:
    actor: Actor
    via: Via
    at: str
    reason: str | None
    change: str
    cause: Cause
    vcs: VcsState
    approvals: tuple[Approval, ...] = field(default=())
    stage: StageLineage | None = None
    """None for an event recorded outside a stage."""

    def to_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "actor": actor_data(self.actor),
            "via": self.via,
            "at": self.at,
            "change": self.change,
            "cause": self.cause.to_data(),
            "approvals": [
                {"actor": actor_data(a.actor), "role": a.role, "at": a.at} for a in self.approvals
            ],
            "vcs": self.vcs.to_data(),
        }
        if self.reason is not None:
            data["reason"] = self.reason
        if self.stage is not None:
            data["stage"] = self.stage.to_data()
        return data


def timestamp(moment: datetime) -> str:
    """RFC 3339 in UTC, with milliseconds and Z."""
    utc = moment.astimezone(UTC)
    # The year is formatted by hand: strftime's %Y doesn't pad years before 1000 on Linux.
    return f"{utc.year:04d}-" + utc.strftime("%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


# Checking lineage data by hand, by the schema's rules. Each check returns the first problem.


def lineage_problem(data: object) -> str | None:
    """What is wrong with ``data`` as lineage, naming the field, or None if it is valid."""
    if not isinstance(data, Mapping):
        return "lineage must be an object"
    problem = _fields("lineage", set(data), _LINEAGE_REQUIRED, {"reason", "stage"})
    if problem:
        return problem
    checks = (
        _actor_problem("actor", data["actor"]),
        None if data["via"] in VIA else f"via must be one of {', '.join(VIA)}",
        _match("at", data["at"], TIME, "an RFC 3339 UTC time with milliseconds and Z"),
        None
        if "reason" not in data or _nonempty(data["reason"])
        else "reason must be a non-empty string, or left out when none was given",
        _match("change", data["change"], ULID, "a ULID"),
        _cause_problem(data["cause"]),
        _approvals_problem(data["approvals"]),
        _vcs_problem(data["vcs"]),
        _stage_problem(data["stage"]) if "stage" in data else None,
    )
    return next((problem for problem in checks if problem), None)


_LINEAGE_REQUIRED = frozenset({"actor", "via", "at", "change", "cause", "approvals", "vcs"})


def _fields(
    where: str, found: Set[str], required: Set[str], optional: Set[str] = frozenset()
) -> str | None:
    """What is wrong with an object's keys: a required one missing, or one it doesn't have."""
    missing, extra = sorted(required - found), sorted(found - required - optional)
    if not missing and not extra:
        return None
    parts = [
        f"missing {', '.join(missing)}" if missing else "",
        f"unexpected {', '.join(extra)}" if extra else "",
    ]
    return f"{where}: " + "; ".join(p for p in parts if p)


def _match(name: str, value: object, pattern: re.Pattern[str], what: str) -> str | None:
    if isinstance(value, str) and pattern.match(value):
        return None
    return f"{name} must be {what}"


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _actor_problem(name: str, actor: object) -> str | None:
    if not isinstance(actor, Mapping):
        return f"{name} must be an object, never null"
    kind = actor.get("kind")
    if kind == "unknown":
        return None if set(actor) == {"kind"} else f"{name}: an unknown actor has only a kind"
    if kind not in ("human", "agent"):
        return f"{name}.kind must be human, agent or unknown"
    problem = _fields(name, set(actor), {"kind", "id", "source"})
    if problem:
        return problem
    if not _nonempty(actor["id"]) or not _nonempty(actor["source"]):
        return f"{name}.id and {name}.source must be non-empty strings"
    return None


def _cause_problem(cause: object) -> str | None:
    if not isinstance(cause, Mapping) or set(cause) != {"kind", "id"}:
        return "cause must be {kind, id}, never null"
    if cause["kind"] == "command":
        return _match("cause.id", cause["id"], ULID, "a ULID for a command cause")
    if cause["kind"] == "event":
        return _match("cause.id", cause["id"], HASH, "a sha256: hash for an event cause")
    return "cause.kind must be command or event"


def _approvals_problem(approvals: object) -> str | None:
    if not isinstance(approvals, list):
        return "approvals must be a list"
    for index, approval in enumerate(approvals):
        where = f"approvals[{index}]"
        if not isinstance(approval, Mapping) or set(approval) != {"actor", "role", "at"}:
            return f"{where} must be {{actor, role, at}}"
        problem = (
            _actor_problem(f"{where}.actor", approval["actor"])
            or (None if _nonempty(approval["role"]) else f"{where}.role must be non-empty")
            or _match(f"{where}.at", approval["at"], TIME, "an RFC 3339 UTC time")
        )
        if problem:
            return problem
    return None


def _vcs_problem(vcs: object) -> str | None:
    if not isinstance(vcs, Mapping):
        return "vcs must be an object"
    problem = _fields("vcs", set(vcs), {"adapter"}, {"branch", "head", "source"})
    if problem:
        return problem
    if not _nonempty(vcs["adapter"]):
        return "vcs.adapter must be a non-empty string"
    for name in ("branch", "head"):
        if name in vcs and not _nonempty(vcs[name]):
            return f"vcs.{name} must be a non-empty string, or left out when there is none"
    if "source" not in vcs:
        return None
    source = vcs["source"]
    if not isinstance(source, Mapping):
        return "vcs.source must be an object, or left out for an event not made from a file"
    problem = _fields("vcs.source", set(source), {"path"}, {"before", "after"})
    if problem:
        return problem
    path = source["path"]
    if not _nonempty(path) or not _theatre_relative(str(path)):
        return "vcs.source.path must be relative to the theatre, with / separators"
    for name in ("before", "after"):
        if name in source and not (isinstance(source[name], str) and HASH.match(source[name])):
            return f"vcs.source.{name} must be a sha256: hash, or left out when there is no file"
    return None


def _stage_problem(stage: object) -> str | None:
    if not isinstance(stage, Mapping):
        return "stage must be an object, or left out for an event recorded outside a stage"
    problem = _fields("stage", set(stage), {"name", "effects"}, {"allowedBy"})
    if problem:
        return problem
    problem = _match("stage.name", stage["name"], STAGE_NAME, "a stage's registered name")
    if problem:
        return problem
    if stage["effects"] == "enforced":
        return (
            None
            if "allowedBy" not in stage
            else "stage.allowedBy must be left out when effects are enforced"
        )
    if stage["effects"] != "unenforced":
        return "stage.effects must be enforced or unenforced"
    allowed = stage.get("allowedBy")
    if not isinstance(allowed, Mapping) or set(allowed) != {"setting", "source"}:
        return "stage.allowedBy must name the setting and source that allowed unenforced effects"
    return _match(
        "stage.allowedBy.setting", allowed["setting"], SETTING_NAME, "a policy setting's name"
    ) or (None if _nonempty(allowed["source"]) else "stage.allowedBy.source must be non-empty")


def _theatre_relative(path: str) -> bool:
    return not (
        path.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:", path)
        or "\\" in path
        or ".." in path.split("/")
    )
