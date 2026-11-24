"""Reading a child writer's outcome from its standard output (its last line, after nothing but
lock-wait announcements, or the test fails naming the line), and a store seeing an event that
another store on the same theatre recorded while its watch was being set up, at once and without
falling back to polling (spec: event-store, "Writers wait for each other, bounded and announced"
and "A subscription delivers other writers' events as they're recorded"; design D10).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_processes.py."""

from pathlib import Path
from uuid import uuid4

import pytest

from processes_shared import Manual, listened, outcome, store_for
from storetesting import (
    event,
)
from troupe.platform.watching import DirectoryWatch

WINDOWS_LOSER = (
    "waiting C:\\Users\\runneradmin\\AppData\\Local\\Temp\\pytest-of-runneradmin\\pytest-0\\"
    "test_two_processes_racing_for_0\\.troupe\\local\\.lock\r\nintegrity-error\r\n"
)
"""A losing racer's real stdout from Windows CI (#43): it announced its wait, then its outcome."""


def test_a_child_s_outcome_is_its_last_line_after_its_announcements() -> None:
    assert outcome(WINDOWS_LOSER) == "integrity-error"
    assert outcome("waiting a\nwaiting b\nrecorded\n") == "recorded"


def test_a_child_s_outcome_without_announcements_is_its_only_line() -> None:
    assert outcome("recorded\r\n") == "recorded"


def test_an_unexpected_line_before_a_child_s_outcome_fails_naming_it() -> None:
    with pytest.raises(AssertionError, match="Traceback"):
        outcome("Traceback (most recent call last):\nrecorded\n")


def test_an_event_recorded_while_the_watch_is_being_set_up_reaches_the_listener_at_once(
    tmp_path: Path,
) -> None:
    other = store_for(tmp_path)  # another session, as another process would be
    other.insert([event(uuid4(), 1)])

    def recording_first(directory: Path) -> DirectoryWatch:
        other.insert([event(uuid4(), 1)])  # after the listener's read, before its watch
        # A watch that never reports: some platforms also report a write made just before a
        # watch starts, which would hide a store that doesn't look again once it is watching.
        return DirectoryWatch(directory, Manual())

    store = store_for(tmp_path, poll_seconds=60, check_seconds=60, watcher=recording_first)
    with listened(store) as heard:
        assert heard.wait(2)
        assert store.max_notification_id() == 2
        assert "events.subscription-polling" not in [n.code for n in store.notices()]
