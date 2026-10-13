"""A pytest plugin that checks every error, notice and recorded event against the protocol as tests
make them (spec: protocol; strict-schemas design D4).

Loaded for every test path through ``addopts`` in pyproject.toml. Each ``TroupeError`` and
``Notice`` is validated against its code's details schema the moment it's constructed, so a raise
site whose details drift from the schema fails the test that reached it. Each payload troupe's
event service records under a topic troupe defines is validated against that topic's schema the
same way. A test that builds an invalid one on purpose does so inside ``unchecked()``.

It also records every code troupe's own source constructs (not the tests). At the end of a full
run (every test path, no ``-k`` or ``-m``), a catalogued code nothing raised fails the session:
each code's schema has to be exercised by real code.
"""

import contextlib
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from catalogues import branches
from protocol_schemas import PROTOCOL_BASE, SCHEMAS, SCRIPTED, load, validator_for
from troupe.core import errors, notices
from troupe.core.events import EventStore

_checking = True
_seen: set[str] = set()
"""Codes troupe's own source constructed during the session."""
SOURCE = "src"


class ProtocolGuardError(AssertionError):
    """An error or notice that doesn't match its code's schema."""


@contextlib.contextmanager
def unchecked() -> Iterator[None]:
    """Construct errors and notices without checking them, for tests that build bad ones."""
    global _checking
    _checking = False
    try:
        yield
    finally:
        _checking = True


def _problems(
    validator: jsonschema.Draft202012Validator, data: object, branch: int | None
) -> list[str]:
    """What's wrong, from the catalogue branch for the code (``branch``, its index in the
    catalogue's oneOf) rather than every branch the data missed."""
    leaves = list(validator.iter_errors(data))
    while any(leaf.context for leaf in leaves):
        leaves = [child for leaf in leaves for child in (leaf.context or [leaf])]

    def in_branch(leaf: jsonschema.ValidationError) -> bool:
        path = list(leaf.absolute_schema_path)
        at = path.index("oneOf") if "oneOf" in path else len(path)
        return at + 1 < len(path) and path[at + 1] == branch

    chosen = [leaf for leaf in leaves if in_branch(leaf)] or leaves
    return sorted(
        {
            f"at {'/'.join(map(str, e.absolute_path)) or 'the top level'}: {e.message}"
            for e in chosen
        }
    )


def _guard(cls: type[Any], catalogue: str, runner: str | None) -> None:
    validator = validator_for(PROTOCOL_BASE + catalogue, runner)
    index = {code: number for number, code in enumerate(branches(catalogue))}
    original = cls.__post_init__

    def __post_init__(self: Any) -> None:  # noqa: ANN401, N807 - wraps the dataclass hook
        original(self)
        # The dataclass's __init__ called this; whoever called that constructed it. Only
        # troupe's own source counts as raising a code: a test that builds one proves nothing.
        caller = Path(sys._getframe(2).f_code.co_filename)
        if SOURCE in caller.parts:
            _seen.add(self.code)
        if not _checking:
            return
        data = self.to_data()
        if not validator.is_valid(data):
            problems = "; ".join(_problems(validator, data, index.get(self.code)))
            msg = (
                f"{cls.__name__} {self.code!r} doesn't match its schema: {problems}. Fix the "
                "details at the raise site, or the code's schema."
            )
            raise ProtocolGuardError(msg) from None

    cls.__post_init__ = __post_init__


def _guard_recording() -> None:
    """Check each payload troupe's event service is about to record, for the topics troupe defines
    (design D4). The hook sits in troupe's service, not the text store, whose own tests run the
    event-sourcing library's recorder suite with topics of its own."""
    record = load(SCHEMAS / "event-record.schema.json")["$defs"]["troupeEvent"]["allOf"]
    schemas = {
        branch["if"]["properties"]["topic"]["const"]: validator_for(
            PROTOCOL_BASE + branch["then"]["properties"]["state"]["$ref"], SCRIPTED
        )
        for branch in record
    }
    original = EventStore._stored

    def _stored(self: EventStore, event: Any, lineage: dict[str, Any]) -> Any:  # noqa: ANN401
        stored = original(self, event, lineage)
        validator = schemas.get(stored.topic)
        if validator is not None and _checking:
            state = json.loads(stored.state)
            if not validator.is_valid(state):
                problems = "; ".join(_problems(validator, state, None))
                msg = (
                    f"the payload of {stored.topic!r} doesn't match its schema: {problems}. Fix "
                    "what the aggregate records, or the topic's schema in protocol/schemas/events/."
                )
                raise ProtocolGuardError(msg)
        return stored

    EventStore._stored = _stored  # type: ignore[method-assign]


def pytest_configure(config: pytest.Config) -> None:
    _guard(errors.TroupeError, "error.schema.json", SCRIPTED)
    _guard(notices.Notice, "notice.schema.json", None)
    _guard_recording()


def _is_full_run(session: pytest.Session) -> bool:
    option = session.config.option
    selecting = ("keyword", "markexpr", "lf", "deselect")
    if any(getattr(option, name, None) for name in selecting):
        return False
    testpaths = session.config.getini("testpaths")
    args = [arg.rstrip("/") for arg in session.config.args]
    return sorted(args) == sorted(testpaths) or not session.config.args


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not _is_full_run(session) or exitstatus != pytest.ExitCode.OK:
        return
    unraised = sorted((set(errors.CODES) | set(notices.CODES)) - _seen)
    if unraised:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(
                "protocol_guard: no test raised these codes, so their details schemas are "
                f"unexercised: {', '.join(unraised)}",
                red=True,
            )
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
