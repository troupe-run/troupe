# troupe-store-text

troupe's text event store. Events are kept as append-only JSON Lines segments under `.troupe/events/`, one per
session per branch, so git merges them without conflicts. Notification order is local and gitignored. It is
both an [`eventsourcing`](https://pypi.org/project/eventsourcing/) persistence module
(`PERSISTENCE_MODULE=troupe_store_text`) and the `text` store in the `troupe.store` entry point group, so troupe finds
it by name and never imports it directly. See [docs/event-store.md](../../docs/event-store.md).
