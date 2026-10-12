# The event store

troupe's state is events, kept as text that git can merge. This page is filled in as the event store is built
(event-store change, task 9.5).

## Defaults

Every limit has its default in `troupe.core.defaults`, and each can be overridden by the caller. The store's write
lock uses the platform's lock defaults (`LOCK_TIMEOUT_SECONDS`, `LOCK_ANNOUNCE_AFTER_SECONDS`).

| Setting | Default |
|---|---|
| `SUBSCRIBE_POLL_SECONDS` | 1 |
