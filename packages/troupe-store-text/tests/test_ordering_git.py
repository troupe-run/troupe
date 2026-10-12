"""Ordering and visibility across branches, merges and removed files, in real git repositories
(spec: event-store; design D5, D7)."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from eventsourcing.persistence import Tracking

from gitrepo import Repo, clone, make_repo
from storetesting import event, segments
from troupe.core import strict_json
from troupe.core.errors import TroupeError
from troupe_store_text.store import TextStore
from troupe_vcs_git import GitAdapter


def store(repo: Repo) -> TextStore:
    """A store reading the theatre from scratch, as a new troupe command would."""
    return TextStore(repo.path, GitAdapter(repo.path, source=repo.env))


def order(repo: Repo) -> list[tuple[int, str]]:
    return [(n, r.id) for n, r in store(repo).notifications(1, 1000, None, ())]


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    made = make_repo(tmp_path)
    made.commit_all("start")
    return made


def test_a_merge_appends_incoming_events_and_never_renumbers(repo: Repo) -> None:
    store(repo).insert([event(uuid4(), 1, on="main")])
    repo.commit_all("main 1")
    repo.git("switch", "-q", "-c", "feature")
    store(repo).insert([event(uuid4(), 1, on="feature")])  # recorded before main's second event
    repo.commit_all("feature 1")
    repo.git("switch", "-q", "main")
    store(repo).insert([event(uuid4(), 1, on="main again")])
    repo.commit_all("main 2")
    before = order(repo)
    assert [n for n, _ in before] == [1, 2]

    repo.git("merge", "-q", "--no-edit", "feature")
    after = order(repo)
    assert after[:2] == before
    assert [n for n, _ in after] == [1, 2, 3]
    assert strict_json.loads(store(repo).event(after[2][1]).state)["on"] == "feature"  # type: ignore[union-attr,index]


def test_two_branches_recording_and_merging_have_no_conflicts_in_the_event_directory(
    repo: Repo,
) -> None:
    stream = uuid4()
    store(repo).insert([event(stream, 1)])
    repo.commit_all("shared start")
    repo.git("switch", "-q", "-c", "feature")
    store(repo).insert([event(uuid4(), 1, side="feature")])
    repo.commit_all("feature")
    repo.git("switch", "-q", "main")
    store(repo).insert([event(uuid4(), 1, side="main")])
    repo.commit_all("main")
    repo.git("merge", "-q", "--no-edit", "feature")  # raises if it conflicts
    assert repo.git("diff", "--name-only", "--diff-filter=U") == ""
    assert len(segments(repo.path)) == 3


def test_uncommitted_events_from_another_branch_are_left_out_and_reported(repo: Repo) -> None:
    stream = uuid4()
    store(repo).insert([event(stream, 1, made="on main, never committed")])
    [segment] = segments(repo.path)
    repo.git("switch", "-q", "-c", "other")  # the untracked segment travels with the switch
    reader = store(repo)
    assert reader.select(stream) == []
    assert reader.max_notification_id() is None
    [notice] = reader.notices()
    assert notice.code == "events.other-branch"
    assert notice.path == str(segment.absolute())
    assert notice.details["branch"] == "main"


def test_an_excluded_events_version_is_free_on_the_current_branch(repo: Repo) -> None:
    stream = uuid4()
    store(repo).insert([event(stream, 1, made="main")])
    repo.git("switch", "-q", "-c", "other")
    store(repo).insert([event(stream, 1, made="other")])  # no integrity error
    assert [r.version for r in store(repo).select(stream)] == [1]


def test_switching_back_shows_the_branchs_own_uncommitted_events_again(repo: Repo) -> None:
    stream = uuid4()
    store(repo).insert([event(stream, 1)])
    repo.git("switch", "-q", "-c", "other")
    repo.git("switch", "-q", "main")
    assert [r.version for r in store(repo).select(stream)] == [1]


def test_committed_events_from_a_merged_branch_are_read(repo: Repo) -> None:
    stream = uuid4()
    repo.git("switch", "-q", "-c", "feature")
    store(repo).insert([event(stream, 1)])
    repo.commit_all("feature events")
    repo.git("switch", "-q", "main")
    assert store(repo).select(stream) == []
    repo.git("merge", "-q", "--no-edit", "feature")
    assert [r.version for r in store(repo).select(stream)] == [1]


def test_removing_an_uncommitted_segment_rebuilds_the_order_and_restarts_followers(
    repo: Repo,
) -> None:
    keep, drop = uuid4(), uuid4()
    store(repo).insert([event(keep, 1)])
    repo.commit_all("kept")
    writer = store(repo)
    writer.insert([event(drop, 1)], tracking=Tracking("projection", 2))
    assert writer.max_tracking_id("projection") == 2
    [dropped] = [
        p for p in segments(repo.path) if p.name in repo.git("status", "--porcelain", "-uall")
    ]
    dropped.unlink()

    reader = store(repo)
    assert reader.max_notification_id() == 1
    assert reader.max_tracking_id("projection") is None
    [notice] = reader.notices()
    assert notice.code == "events.order-rebuilt"
    assert notice.details["gone"] == 1
    assert "no longer here" in notice.problem


def test_a_parent_whose_file_was_removed_by_hand_is_refused_with_the_fix(repo: Repo) -> None:
    stream = uuid4()
    store(repo).insert([event(stream, 1)])
    store(repo).insert([event(stream, 2)])
    first, second = segments(repo.path)
    first.unlink()
    with pytest.raises(TroupeError) as caught:
        store(repo).select(stream)
    assert caught.value.code == "events.missing-parent"
    assert caught.value.path == str(second.absolute())
    assert "Restore the file" in caught.value.fix
    assert "remove this file too" in caught.value.fix
    assert caught.value.details["missing_parent"].startswith("sha256:")


def test_a_parent_only_in_another_branchs_uncommitted_segment_is_missing_and_named(
    repo: Repo,
) -> None:
    stream = uuid4()
    repo.git("switch", "-q", "-c", "feature")
    store(repo).insert([event(stream, 1)])  # stays uncommitted
    store(repo).insert([event(stream, 2)])  # a second session: its own segment
    parent_segment, child_segment = segments(repo.path)
    repo.git("add", str(child_segment.relative_to(repo.path)))
    repo.git("commit", "-q", "-m", "only the child")
    repo.git("switch", "-q", "main")
    repo.git("merge", "-q", "--no-edit", "feature")
    with pytest.raises(TroupeError) as caught:
        store(repo).select(stream)
    assert caught.value.code == "events.missing-parent"
    assert caught.value.details["only_in"] == [str(parent_segment)]


def test_two_clones_making_the_same_change_record_one_event_with_both_lineages(
    tmp_path: Path, repo: Repo
) -> None:
    other = clone(repo, tmp_path, "other")
    stream = UUID(int=7)
    for theatre, who in ((repo, "ada"), (other, "grace")):
        store(theatre).insert([event(stream, 1, value=3, lineage={"actor": who})])
        theatre.commit_all(f"{who}'s change")
    repo.git("pull", "-q", "--no-rebase", "--no-edit", str(other.path), "main")

    reader = store(repo)
    [single] = reader.select(stream)
    lineages = [r.lineage for r in reader.recordings(single.id)]
    assert sorted(lineage["actor"] for lineage in lineages if lineage) == ["ada", "grace"]
    assert reader.max_notification_id() == 1
