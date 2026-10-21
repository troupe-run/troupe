"""Reading and recording the config stream (spec: config; config-model design D2 to D5).

``read`` works out config from the stream's whole history (``troupe.core.config.merge``), and
records nothing. ``record`` records one command's change: refused, recording nothing, when it
would leave config invalid, or leave any conflict unresolved; and when the stream has forked, the
same batch first settles the fork, with the merged config as the settled state.
"""

from collections.abc import Sequence
from typing import Any

from eventsourcing.utils import get_topic

from troupe.core.config import aggregate
from troupe.core.config.changes import apply
from troupe.core.config.kinds import check
from troupe.core.config.merge import Change, Merged, merge
from troupe.core.errors import TroupeError
from troupe.core.events import Command, EventStore, Recorded


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


def record(
    command: Command,
    merged: Merged,
    entries: Sequence[dict[str, Any]],
    files: Sequence[dict[str, Any]],
) -> list[Recorded]:
    """Record ``entries`` as one ``Config.Changed`` after ``merged``, the config they were
    worked out from. Refused, recording nothing, when the config they make breaks a rule, or when
    there are conflicts it leaves unresolved."""
    after = apply(merged.config, entries)
    check(after)
    if merged.conflicts:
        proposed = Change("proposed", command.change, {}, "", tuple(entries), tuple(files))
        refuse_conflicts(merge(command.store.history(aggregate.STREAM), extra=proposed))
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
