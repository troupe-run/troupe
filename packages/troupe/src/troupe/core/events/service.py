"""The event-store service: every event troupe records goes through here (spec: event-store,
lineage, identity; design D1, D6, D8, D9).

A command resolves who is acting before anything is written (a command with no identity fails), and
mints the change id every event that follows from it shares. Each event's lineage is checked against
the schema's rules, and its cause against the store, before the store is called; an invalid one
writes nothing. A reaction to an event inherits that event's change id and names it as its cause.
A fork is settled by an event that names every head and carries the settled state.
"""

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from eventsourcing.domain import Aggregate, DomainEventProtocol
from eventsourcing.persistence import (
    DatetimeAsISO,
    DecimalAsStr,
    IntegrityError,
    JSONTranscoder,
    Mapper,
    StoredEvent,
    UUIDAsHex,
)
from eventsourcing.utils import get_topic

from troupe.core import defaults, strict_json
from troupe.core.errors import TroupeError
from troupe.core.events.lineage import (
    Actor,
    Cause,
    CommandCause,
    EventCause,
    Lineage,
    Source,
    VcsState,
    Via,
    lineage_problem,
    timestamp,
)
from troupe.core.events.port import EventRecorder, RecordedEvent, load_store
from troupe.core.events.settling import Settled
from troupe.core.identity import IdentityContext, IdentitySource, resolve_identity
from troupe.core.notices import Notice
from troupe.core.ulid import new_ulid
from troupe.core.vcs import Vcs, load_vcs

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


class CanonicalTranscoder(JSONTranscoder):
    """The library's JSON transcoder, writing canonical JSON (sorted keys, no NaN), so troupe's
    events are stored inline and readable in a diff (design D3)."""

    def __init__(self) -> None:
        super().__init__()
        self.encoder = self.encoder.__class__(
            default=self._encode_obj,
            separators=(",", ":"),
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        for transcoding in (UUIDAsHex(), DecimalAsStr(), DatetimeAsISO()):
            self.register(transcoding)


@dataclass(frozen=True)
class Recorded:
    """A recorded event's notification id and content-hash id."""

    notification_id: int
    event_id: str


class EventStore:
    """The theatre's events, read and written with lineage."""

    def __init__(
        self,
        theatre: Path,
        *,
        vcs: Vcs,
        recorder: EventRecorder,
        env: Mapping[str, str] | None = None,
        clock: Clock = utc_now,
        identity_chain: Sequence[str] = defaults.IDENTITY_CHAIN,
        identity_sources: Sequence[tuple[str, IdentitySource]] | None = None,
    ) -> None:
        self.theatre = theatre
        self.vcs = vcs
        self.recorder = recorder
        self.env = os.environ if env is None else env
        self.clock = clock
        self.identity_chain = identity_chain
        self.identity_sources = identity_sources
        self.mapper: Mapper[UUID] = Mapper(transcoder=CanonicalTranscoder())

    @classmethod
    def open(
        cls,
        theatre: Path,
        *,
        vcs: str = "git",
        store: str = "text",
        env: Mapping[str, str] | None = None,
        clock: Clock = utc_now,
    ) -> "EventStore":
        """The theatre's event store, with its VCS adapter and store found by name."""
        adapter = load_vcs(vcs, theatre)
        return cls(
            theatre, vcs=adapter, recorder=load_store(store, theatre, adapter), env=env, clock=clock
        )

    # Commands.

    def identify(self) -> Actor:
        """Who is acting, through the identity chain; fails when nobody can be identified."""
        context = IdentityContext(env=self.env, vcs=self.vcs)
        return resolve_identity(context, chain=self.identity_chain, sources=self.identity_sources)

    def command(
        self, *, via: Via, reason: str | None = None, actor: Actor | None = None
    ) -> "Command":
        """Start a command: resolve the actor (unless given, as for an agent troupe runs or an
        unknown hand edit) and mint its change id. Nothing is written yet."""
        return Command(
            self, actor=self.identify() if actor is None else actor, via=via, reason=reason
        )

    def vcs_state(self, source: Source | None = None) -> VcsState:
        return VcsState(
            adapter=self.vcs.name, branch=self.vcs.branch(), head=self.vcs.head(), source=source
        )

    def record_reaction(
        self,
        trigger: str,
        events: Sequence[DomainEventProtocol[UUID]],
        *,
        via: Via,
        actor: Actor | None = None,
        reason: str | None = None,
    ) -> list[Recorded]:
        """Record ``events`` in reaction to the event ``trigger``: they carry its change id and
        name it as their cause (design D8)."""
        triggered = self.recorder.event(trigger)
        if triggered is None:
            raise _cause_unknown(trigger)
        trigger_lineage = triggered.lineage
        if trigger_lineage is None or not isinstance(trigger_lineage.get("change"), str):
            raise TroupeError(
                "events.cause-unknown",
                problem=f"Event {trigger} has no lineage, so there's no change id to carry on.",
                fix="React only to events troupe recorded.",
                details={"cause": trigger},
            )
        lineage = Lineage(
            actor=self.identify() if actor is None else actor,
            via=via,
            at=timestamp(self.clock()),
            reason=reason,
            change=trigger_lineage["change"],
            cause=EventCause(trigger),
            vcs=self.vcs_state(),
        )
        return self.record_with_lineage(events, lineage)

    def record_with_lineage(
        self,
        events: Sequence[DomainEventProtocol[UUID]],
        lineage: Lineage,
        *,
        settling_parents: Sequence[str] | None = None,
    ) -> list[Recorded]:
        """Record ``events`` with ``lineage``, checked first: an invalid one writes nothing."""
        data = lineage.to_data()
        problem = lineage_problem(data)
        if problem is not None:
            raise TroupeError(
                "events.lineage-invalid",
                problem=f"An event's lineage isn't valid: {problem}.",
                fix="This is a bug in whatever built the lineage: every event troupe records must "
                "name its actor, via, time, change, cause and VCS state.",
                details={"problem": problem},
            )
        self._check_cause(lineage.cause, lineage.change)
        stored = [self._stored(event, data) for event in events]
        try:
            numbers = self.recorder.insert(stored, settling_parents=settling_parents)
        except IntegrityError as error:
            raise TroupeError(
                "events.version-conflict",
                problem=f"Another change was recorded first: {error}.",
                fix="Load the latest state and try the command again.",
                details={"reason": str(error)},
            ) from error
        if not numbers:
            return []
        ordered = self.recorder.notifications(numbers[0], len(numbers), numbers[-1], ())
        return [Recorded(n, record.id) for n, record in ordered]

    def _check_cause(self, cause: Cause, change: str) -> None:
        if isinstance(cause, CommandCause):
            if cause.id != change:
                raise TroupeError(
                    "events.lineage-invalid",
                    problem=f"An event's command cause ({cause.id}) isn't its change id "
                    f"({change}).",
                    fix="A command's own events name the command's change id as their cause.",
                    details={"cause": cause.id, "change": change},
                )
            return
        if self.recorder.event(cause.id) is None:
            raise _cause_unknown(cause.id)

    def _stored(self, event: DomainEventProtocol[UUID], lineage: dict[str, Any]) -> StoredEvent:
        stored = self.mapper.to_stored_event(event)
        state = strict_json.loads(stored.state)
        if not isinstance(state, dict):
            msg = "an event's state must be a JSON object"
            raise TypeError(msg)
        state["lineage"] = lineage
        return StoredEvent(
            originator_id=stored.originator_id,
            originator_version=stored.originator_version,
            topic=stored.topic,
            state=strict_json.dumps(state).encode("utf-8"),
        )

    # Reads.

    def load(self, stream: UUID) -> Aggregate | None:
        """The stream's current state, from its latest settling event (or its start) to its single
        head. A forked stream, or one missing a parent, is refused."""
        aggregate: Aggregate | None = None
        for record in self.recorder.select(stream):
            event = self.mapper.to_domain_event(
                StoredEvent(
                    originator_id=record.stream,
                    originator_version=record.version,
                    topic=record.topic,
                    state=record.state,
                )
            )
            mutate = getattr(event, "mutate")  # noqa: B009 - every stored domain event can mutate
            aggregate = mutate(aggregate)
        return aggregate

    def history(self, stream: UUID) -> list[RecordedEvent]:
        """Every event of the stream, both sides of any fork, in order."""
        return list(self.recorder.history(stream))

    def recordings(self, event: str) -> list[dict[str, Any] | None]:
        """The lineage of every recording of ``event``."""
        return [r.lineage for r in self.recorder.recordings(event)]

    def forks(self) -> list[UUID | str]:
        return self.recorder.forks()

    def notices(self) -> list[Notice]:
        return self.recorder.notices()


class Command:
    """One command: an actor, a surface, a reason and a change id shared by all it records."""

    def __init__(self, store: EventStore, *, actor: Actor, via: Via, reason: str | None) -> None:
        self.store = store
        self.actor = actor
        self.via = via
        self.reason = reason
        self.change = new_ulid()

    def lineage(self, source: Source | None = None) -> Lineage:
        return Lineage(
            actor=self.actor,
            via=self.via,
            at=timestamp(self.store.clock()),
            reason=self.reason,
            change=self.change,
            cause=CommandCause(self.change),
            vcs=self.store.vcs_state(source),
        )

    def record(
        self, events: Sequence[DomainEventProtocol[UUID]], *, source: Source | None = None
    ) -> list[Recorded]:
        """Record ``events`` as this command's own, all or nothing."""
        return self.store.record_with_lineage(events, self.lineage(source))

    def settle(self, aggregate: Aggregate) -> Recorded:
        """End the fork in ``aggregate``'s stream with ``aggregate`` as the settled state: a
        settling event whose parents are every head (design D6)."""
        heads = self.store.recorder.heads(aggregate.id)
        state = {
            k: v
            for k, v in vars(aggregate).items()
            if k not in ("_id", "_version", "_pending_events")
        }
        settled = Settled(
            originator_id=aggregate.id,
            originator_version=max((h.version for h in heads), default=0) + 1,
            timestamp=Settled.create_timestamp(),
            topic=get_topic(type(aggregate)),
            state=state,
        )
        [recorded] = self.store.record_with_lineage(
            [settled], self.lineage(), settling_parents=[h.id for h in heads]
        )
        return recorded


def _cause_unknown(event: str) -> TroupeError:
    return TroupeError(
        "events.cause-unknown",
        problem=f"An event names {event} as its cause, but no such event is recorded here.",
        fix="Name an event recorded on this branch as the cause.",
        details={"cause": event},
    )
