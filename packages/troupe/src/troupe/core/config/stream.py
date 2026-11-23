"""Reading and recording the config stream (spec: config; config-model design D2 to D5).

``read`` works out config from the stream's whole history (``troupe.core.config.merge``), and
records nothing. ``record`` records one command's change: refused, recording nothing, when it
would leave config invalid, or leave any conflict unresolved; and when the stream has forked, the
same batch first settles the fork, with the merged config as the settled state.
"""

from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from eventsourcing.utils import get_topic

from troupe.core.config import aggregate
from troupe.core.config.changes import apply
from troupe.core.config.kinds import ACTORS, check
from troupe.core.config.merge import Change, Merged, merge
from troupe.core.errors import TroupeError
from troupe.core.events import Command, EventStore, Recorded

if TYPE_CHECKING:
    from troupe.core.config.sweep import Edit


def read(store: EventStore) -> Merged:
    """Config as the stream's history works it out, branches merged. Records nothing."""
    return merge(store.history(aggregate.STREAM))


def refuse_conflicts(merged: Merged) -> None:
    """Refuse with ``config.conflict`` when config has any conflict, naming each and the fix."""
    if not merged.conflicts:
        return
    listed = " ".join(f"({n}) {c.describe()}." for n, c in enumerate(merged.conflicts, start=1))
    raise TroupeError(
        "config.conflict",
        problem=f"Branches' config changes conflict, so config can't be used until they're "
        f"resolved: {listed}",
        fix="Resolve each with one troupe config set (or unset) that sets every value named "
        "above. troupe config get shows both sides.",
        details={
            "conflicts": [
                {
                    "paths": [list(path) for path in conflict.paths],
                    "changes": [c.change for c in conflict.changes],
                    **({"rule": conflict.rule} if conflict.rule is not None else {}),
                }
                for conflict in merged.conflicts
            ]
        },
    )


def refuse_unrecordable(
    store: EventStore,
    merged: Merged,
    entries: Sequence[dict[str, Any]],
    typed: Collection[tuple[str, ...]] | None = None,
) -> None:
    """Refuse, recording nothing, a change whose config breaks a rule, or that leaves a conflict
    unresolved: it's merged as though recorded after every head, and must leave none. ``typed`` are
    the paths the person typed, so a key from inside a value they set isn't repeated
    (kinds.Typed)."""
    after = apply(merged.config, entries)
    # The actors this change sets or unsets anything under and leaves in config: one on a runner
    # that isn't installed is refused, since its options can't be checked (runner-extras D7).
    touched = {
        str(entry["path"][1])
        for entry in entries
        if len(entry["path"]) > 1 and entry["path"][0] == ACTORS
    }
    # actors may not be a group at all, which check refuses with config.invalid: nothing to touch.
    actors = after.get(ACTORS)
    check(after, touched & set(actors) if isinstance(actors, Mapping) else set(), typed)
    if merged.conflicts:
        proposed = Change("proposed", "", {}, "", tuple(entries), ())
        refuse_conflicts(merge(store.history(aggregate.STREAM), extra=proposed))


def record(
    command: Command,
    merged: Merged,
    entries: Sequence[dict[str, Any]],
    files: Sequence[dict[str, Any]],
) -> list[Recorded]:
    """Record ``entries`` as one ``Config.Changed`` after ``merged``, the config they were
    worked out from. Refused, recording nothing, when the config they make breaks a rule, or when
    there are conflicts it leaves unresolved."""
    refuse_unrecordable(command.store, merged, entries)
    version = merged.version + 1
    if len(merged.heads) > 1:
        settled = aggregate.Config.Settled(
            originator_id=aggregate.STREAM,
            originator_version=version,
            timestamp=aggregate.Config.Settled.create_timestamp(),
            topic=get_topic(aggregate.Config),
            state={"config": merged.config},
        )
        change = aggregate.changed(version + 1, list(entries), list(files))
        return command.record([settled, change], settles=list(merged.heads))
    return command.record([aggregate.changed(version, list(entries), list(files))])


def record_with_edits(
    store: EventStore,
    merged: Merged,
    edits: Sequence["Edit"],
    own: tuple[Command, Sequence[dict[str, Any]], Sequence[dict[str, Any]]] | None = None,
    typed: Collection[tuple[str, ...]] | None = None,
    *,
    own_first: bool = False,
) -> list[Recorded]:
    """Record a sweep's hand edits, one ``Config.Changed`` per file by the unknown author, then,
    with ``own``, a command's own change, all in one batch after ``merged`` (spec:
    config-hand-edits; hand-edit-sweep design D7, D8). Refused, recording nothing, when the config
    they make together breaks a rule, or leaves a conflict unresolved. When the stream has forked,
    the batch first settles it. The sweep's changes share one change id of their own. With
    ``own_first``, the command's change is recorded before the sweep's, which were worked out on
    the config it leaves (a rename of files a person already moved; config-mv design D5)."""
    from troupe.core.events import Source, Unknown
    from troupe.core.theatre import THEATRE_DIR

    swept = [entry for edit in edits for entry in edit.entries]
    mine = list(own[1]) if own is not None else []
    entries = [*mine, *swept] if own_first else [*swept, *mine]
    if not entries:
        return []
    refuse_unrecordable(store, merged, entries, typed)
    sweep = store.command(via="file", actor=Unknown()) if edits else None
    events: list[Any] = []
    lineages: list[Any] = []
    version = merged.version + 1
    forked = len(merged.heads) > 1
    first = own[0] if own_first and own is not None else sweep
    if first is None and own is not None:
        first = own[0]
    if forked and first is not None:
        events.append(
            aggregate.Config.Settled(
                originator_id=aggregate.STREAM,
                originator_version=version,
                timestamp=aggregate.Config.Settled.create_timestamp(),
                topic=get_topic(aggregate.Config),
                state={"config": merged.config},
            )
        )
        lineages.append(first.lineage())
        version += 1

    def record_own() -> None:
        nonlocal version
        if own is not None and own[1]:
            command, own_entries, files = own
            events.append(aggregate.changed(version, list(own_entries), list(files)))
            lineages.append(command.lineage())
            version += 1

    if own_first:
        record_own()
    if sweep is not None:
        for edit in edits:
            events.append(aggregate.changed(version, list(edit.entries), list(edit.files)))
            path = f"{THEATRE_DIR}/{edit.path}"
            lineages.append(sweep.lineage(Source(path=path, before=edit.before, after=edit.after)))
            version += 1
    if not own_first:
        record_own()
    return store.record_with_lineages(
        events, lineages, settling_parents=list(merged.heads) if forked else None
    )
