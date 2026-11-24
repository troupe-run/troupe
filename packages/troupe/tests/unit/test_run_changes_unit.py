"""A run summary's changes must fit where the run worked: a run in the theatre that has changes, and
pending changes without a diff, are refused by the schema and by the client message classes
(spec: run-workspaces; worktree-stage design D6; account-for-every-worktree design D5, D6).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_run_changes.py."""

import pytest

from troupe.core.client import messages as m


def test_a_summary_in_the_theatre_with_changes_doesnt_validate() -> None:
    from client_messages_shared import ENDED_SUMMARY
    from client_schemas import is_valid

    summary = {**ENDED_SUMMARY, "changes": {"state": "none", "worktree": ".troupe/local/w"}}
    assert not is_valid({"run": summary}, "perform-result.schema.json")
    with pytest.raises(ValueError, match="changes are present exactly when"):
        m.RunSummary.from_data(summary)


def test_pending_changes_without_a_diff_dont_validate() -> None:
    from client_schemas import is_valid

    changes = {"state": "pending", "worktree": ".troupe/local/w"}
    assert not is_valid(changes, "run.schema.json#/$defs/changes")
    with pytest.raises(ValueError, match="pending changes have a diff"):
        m.ChangesData.from_data(changes)
