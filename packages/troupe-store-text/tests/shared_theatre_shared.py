"""What test_shared_theatre.py and test_shared_theatre_integration.py share."""

from troupe_store_text.store import TextStore


def ordered(store: TextStore) -> list[tuple[int, str]]:
    return [(n, record.id) for n, record in store.notifications(1, 100_000, None, ())]
