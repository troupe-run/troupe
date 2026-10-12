"""The settling event: how a fork ends (spec: event-store; design D6).

A stream appended to on two branches has two heads, and loading it is refused. A settling event
names every head as its parent and carries the settled state, following the library's Snapshot
mechanics: its ``mutate(None)`` builds the aggregate from that state. Loading a settled stream
starts from the settling event, so no event from either branch before it is applied, and nobody's
branch wins by default. What the settled state is, is the aggregate's business (config's
three-way merge).
"""

from eventsourcing.domain import Snapshot


class Settled(Snapshot):
    """Ends a fork: its parents are every head, and its state is the settled aggregate."""
