"""Segments, batches and the local files (spec: event-store; design D2, D4, D5)."""

import json
from pathlib import Path
from uuid import UUID

import pytest
from eventsourcing.persistence import IntegrityError, Tracking

from storetesting import event, fresh_store, new_stream, segments, snapshot
from troupe.core.errors import TroupeError
from troupe_store_text.store import TextStore


@pytest.fixture
def theatre(tmp_path: Path) -> Path:
    return tmp_path


def lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_bytes().splitlines()]


def test_a_session_writes_its_header_with_its_first_batch_and_appends_after(
    theatre: Path,
) -> None:
    store = fresh_store(theatre)
    stream = new_stream()
    store.insert([event(stream, 1, n=1)])
    store.insert([event(stream, 2, n=2)])
    [segment] = segments(theatre)
    header, first, second = lines(segment)
    assert header == {
        "format": 1,
        "segment": {"session": segment.stem, "vcs": "files", "branch": None},
    }
    assert (first["version"], second["version"]) == (1, 2)
    assert second["parents"] == [first["id"]]


def test_each_session_has_its_own_segment(theatre: Path) -> None:
    fresh_store(theatre).insert([event(new_stream(), 1)])
    fresh_store(theatre).insert([event(new_stream(), 1)])
    assert len(segments(theatre)) == 2


def test_a_batch_is_one_run_of_lines_that_name_their_batch(theatre: Path) -> None:
    stream = new_stream()
    fresh_store(theatre).insert([event(stream, 1), event(stream, 2), event(stream, 3)])
    _, *batch = lines(segments(theatre)[0])
    assert [line["batch"]["index"] for line in batch] == [0, 1, 2]  # type: ignore[index]
    assert {line["batch"]["size"] for line in batch} == {3}  # type: ignore[index]
    assert len({line["batch"]["id"] for line in batch}) == 1  # type: ignore[index]


def test_a_duplicate_version_raises_the_integrity_error_and_writes_nothing(
    theatre: Path,
) -> None:
    store = fresh_store(theatre)
    stream = new_stream()
    store.insert([event(stream, 1)])
    before = snapshot(theatre / ".troupe")
    with pytest.raises(IntegrityError):
        store.insert([event(stream, 1, other=True)])
    assert snapshot(theatre / ".troupe") == before


def test_a_conflict_at_the_end_of_a_batch_records_none_of_it(theatre: Path) -> None:
    store = fresh_store(theatre)
    stream, other = new_stream(), new_stream()
    store.insert([event(stream, 1)])
    with pytest.raises(IntegrityError):
        store.insert([event(other, 1), event(other, 2), event(stream, 1)])
    assert store.select(other) == []


def _two_batches(theatre: Path) -> tuple[Path, bytes, UUID]:
    store = fresh_store(theatre)
    stream = new_stream()
    store.insert([event(stream, 1)])
    store.insert([event(stream, 2), event(stream, 3)])
    [segment] = segments(theatre)
    return segment, segment.read_bytes(), stream


def test_a_batch_cut_off_mid_line_is_left_out_and_reported(theatre: Path) -> None:
    segment, data, stream = _two_batches(theatre)
    last_line_starts = data.rfind(b"\n", 0, len(data) - 1) + 1
    segment.write_bytes(data[: last_line_starts + 20])  # cut inside the batch's last line
    reader = fresh_store(theatre)
    assert [r.version for r in reader.history(stream)] == [1]
    assert [r.version for r in reader.select(stream)] == [1]
    [notice] = reader.notices()
    assert notice.code == "events.incomplete-batch"
    assert notice.path == str(segment.absolute())


def test_a_batch_missing_its_last_line_is_left_out_and_reported(theatre: Path) -> None:
    segment, data, stream = _two_batches(theatre)
    segment.write_bytes(data[: data.rfind(b"\n", 0, len(data) - 1) + 1])  # drop the last line
    reader = fresh_store(theatre)
    assert [r.version for r in reader.history(stream)] == [1]
    assert [n.code for n in reader.notices()] == ["events.incomplete-batch"]


def test_a_malformed_line_before_the_end_fails_naming_the_file_and_line(theatre: Path) -> None:
    segment, data, _ = _two_batches(theatre)
    header, first, *rest = data.splitlines(keepends=True)
    segment.write_bytes(header + first.replace(b'"version":1', b'"version":"1"') + b"".join(rest))
    with pytest.raises(TroupeError) as caught:
        fresh_store(theatre).max_notification_id()
    assert caught.value.code == "events.malformed-record"
    assert caught.value.path == str(segment.absolute())
    assert caught.value.details["line"] == 2


def test_an_incomplete_batch_followed_by_another_batch_is_damage_not_an_interruption(
    theatre: Path,
) -> None:
    segment, data, _ = _two_batches(theatre)
    header, first, second, _ = data.splitlines(keepends=True)
    segment.write_bytes(header + first + second + first)  # batch 2 is cut, then a line follows
    with pytest.raises(TroupeError) as caught:
        fresh_store(theatre).max_notification_id()
    assert caught.value.code == "events.malformed-record"


def test_reads_create_and_change_no_file_in_the_event_directory(theatre: Path) -> None:
    stream = new_stream()
    fresh_store(theatre).insert([event(stream, 1), event(stream, 2)])
    before = snapshot(theatre / ".troupe" / "events")
    reader = fresh_store(theatre)
    reader.select(stream)
    reader.history(stream)
    reader.heads(stream)
    reader.forks()
    reader.notices()
    reader.notifications(1, 10, None, ())
    reader.max_notification_id()
    reader.max_tracking_id("app")
    assert snapshot(theatre / ".troupe" / "events") == before


def test_reading_a_theatre_with_no_events_creates_nothing(theatre: Path) -> None:
    reader = fresh_store(theatre)
    assert reader.select(new_stream()) == []
    assert reader.max_notification_id() is None
    assert reader.notices() == []
    assert not (theatre / ".troupe").exists()


def test_the_first_write_adds_troupes_gitignore_and_gitattributes_only_when_missing(
    theatre: Path,
) -> None:
    (theatre / ".troupe").mkdir()
    (theatre / ".troupe" / ".gitattributes").write_text("# mine\n", encoding="utf-8")
    fresh_store(theatre).insert([event(new_stream(), 1)])
    assert (theatre / ".troupe" / ".gitignore").read_text(encoding="utf-8").endswith("local/\n")
    assert (theatre / ".troupe" / ".gitattributes").read_text(encoding="utf-8") == "# mine\n"


def test_notification_ids_are_dense_and_survive_reopening(theatre: Path) -> None:
    store = fresh_store(theatre)
    streams = [new_stream() for _ in range(3)]
    assert store.insert([event(streams[0], 1), event(streams[1], 1)]) == [1, 2]
    assert store.insert([event(streams[2], 1)]) == [3]
    before = [(n, r.id) for n, r in store.notifications(1, 10, None, ())]
    after = [(n, r.id) for n, r in fresh_store(theatre).notifications(1, 10, None, ())]
    assert after == before
    assert [n for n, _ in after] == [1, 2, 3]


def test_no_tracked_file_holds_notification_ids(theatre: Path) -> None:
    fresh_store(theatre).insert([event(new_stream(), 1)])
    for path in segments(theatre):
        assert '"n":' not in path.read_text(encoding="utf-8")
    assert (theatre / ".troupe" / "local" / "order").is_dir()


# The local files are read strictly too (design D3, D5).


def _local_file(theatre: Path, kind: str) -> Path:
    [path] = (theatre / ".troupe" / "local" / kind).glob("*.jsonl")
    return path


def _with_tracking(theatre: Path) -> TextStore:
    store = fresh_store(theatre)
    store.insert([event(new_stream(), 1)], tracking=Tracking("upstream", 1))
    return store


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(b'{"n":2,"event":"sha256:x","n":2}\n', id="duplicate key"),
        pytest.param(b'{"n":NaN,"event":"sha256:x"}\n', id="NaN"),
    ],
)
def test_a_duplicate_key_or_nan_in_the_order_log_is_refused(theatre: Path, bad: bytes) -> None:
    _with_tracking(theatre)
    path = _local_file(theatre, "order")
    path.write_bytes(path.read_bytes() + bad + b'{"n":3,"event":"sha256:y"}\n')
    with pytest.raises(TroupeError) as caught:
        fresh_store(theatre).max_notification_id()
    assert caught.value.code == "events.malformed-record"
    assert caught.value.path == str(path.absolute())


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(
            b'{"epoch":"e","application_name":"a","application_name":"b","notification_id":1}\n',
            id="duplicate key",
        ),
        pytest.param(
            b'{"epoch":"e","application_name":"a","notification_id":Infinity}\n', id="Infinity"
        ),
    ],
)
def test_a_duplicate_key_or_infinity_in_the_tracking_file_is_refused(
    theatre: Path, bad: bytes
) -> None:
    _with_tracking(theatre)
    path = _local_file(theatre, "tracking")
    path.write_bytes(bad + path.read_bytes())
    with pytest.raises(TroupeError) as caught:
        fresh_store(theatre).max_tracking_id("upstream")
    assert caught.value.code == "events.malformed-record"


def test_a_torn_last_tracking_line_is_ignored_and_trimmed(theatre: Path) -> None:
    _with_tracking(theatre)
    path = _local_file(theatre, "tracking")
    whole = path.read_bytes()
    path.write_bytes(whole + b'{"epoch":"e","applic')
    assert fresh_store(theatre).max_tracking_id("upstream") == 1
    assert path.read_bytes() == whole
