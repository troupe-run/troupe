"""Tests for the artifact store (spec: artifact-store)."""

import hashlib
import subprocess
from pathlib import Path

import jsonschema
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from runner_schemas import SCHEMAS, load
from troupe.core.artifacts import (
    ArtifactStore,
    LocalArtifactStore,
    MemoryArtifactStore,
    reference,
)
from troupe.core.errors import TroupeError

ERROR_SCHEMA = load(SCHEMAS / "error.schema.json")


def _stores(tmp_path: Path) -> list[ArtifactStore]:
    return [LocalArtifactStore(tmp_path / "artifacts"), MemoryArtifactStore()]


def _temporary_files(store: LocalArtifactStore) -> list[Path]:
    return list((store.root / "tmp").iterdir())


# Requirement: Artifacts are addressed by their SHA-256 hash


@pytest.mark.parametrize("kind", ["local", "memory"])
def test_the_reference_is_sha256_and_the_hex_digest_of_the_bytes(tmp_path: Path, kind: str) -> None:
    store = _stores(tmp_path)[0 if kind == "local" else 1]
    ref = store.put(b"hello\n")
    assert ref == "sha256:" + hashlib.sha256(b"hello\n").hexdigest()
    assert store.read(ref) == b"hello\n"


def test_storing_the_same_bytes_twice_returns_one_reference_and_keeps_one_copy(
    tmp_path: Path,
) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    first = store.put(b"same")
    second = store.put(b"same")
    assert first == second
    stored = [path for path in (store.root / "sha256").rglob("*") if path.is_file()]
    assert stored == [store.path_for(first)]
    assert _temporary_files(store) == []


@settings(max_examples=50, deadline=None)
@given(data=st.binary(max_size=4096))
def test_any_bytes_round_trip_under_their_own_sha256(
    tmp_path_factory: pytest.TempPathFactory, data: bytes
) -> None:
    store = LocalArtifactStore(tmp_path_factory.mktemp("store"))
    ref = store.put(data)
    assert ref == reference(data) == "sha256:" + hashlib.sha256(data).hexdigest()
    assert store.read(ref) == data


# Requirement: Artifacts can be written as a stream


@pytest.mark.parametrize("kind", ["local", "memory"])
def test_a_64_mib_artifact_written_in_4_kib_pieces_is_referenced_by_the_hash_of_all_of_them(
    tmp_path: Path, kind: str
) -> None:
    store = _stores(tmp_path)[0 if kind == "local" else 1]
    expected = hashlib.sha256()
    with store.open_writer() as writer:
        for index in range(16 * 1024):
            piece = index.to_bytes(4, "big") * 1024
            writer.write(piece)
            expected.update(piece)
        ref = writer.finish()
    assert ref == "sha256:" + expected.hexdigest()
    assert store.contains(ref)


def test_an_unfinished_artifact_cannot_be_read(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    writer = store.open_writer()
    writer.write(b"partial")
    assert not store.contains(reference(b"partial"))
    with pytest.raises(TroupeError) as caught:
        store.read(reference(b"partial"))
    assert caught.value.code == "artifact.missing"
    writer.abort()


# Requirement: Writes are atomic and leave nothing behind on failure


def test_an_abandoned_write_leaves_nothing_readable_and_no_temporary_file(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    writer = store.open_writer()
    writer.write(b"half an artifact")
    writer.abort()
    assert not store.contains(reference(b"half an artifact"))
    assert _temporary_files(store) == []
    assert [path for path in (store.root / "sha256").rglob("*") if path.is_file()] == []


def test_an_exception_inside_the_writer_block_abandons_the_artifact(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")

    def crash_while_writing() -> None:
        with store.open_writer() as writer:
            writer.write(b"never finished")
            raise RuntimeError("the run crashed")

    with pytest.raises(RuntimeError):
        crash_while_writing()
    assert _temporary_files(store) == []
    assert not store.contains(reference(b"never finished"))


def test_a_finished_writer_refuses_more_writes(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    with store.open_writer() as writer:
        writer.write(b"done")
        writer.finish()
        with pytest.raises(ValueError, match="already finished"):
            writer.write(b"more")


# Requirement: Reads are verified


def test_reading_an_artifact_altered_after_it_was_stored_fails_naming_the_reference_and_path(
    tmp_path: Path,
) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    ref = store.put(b"original")
    path = store.path_for(ref)
    path.write_bytes(b"tampered")
    with pytest.raises(TroupeError) as caught:
        store.read(ref)
    error = caught.value
    assert error.code == "artifact.corrupt"
    assert ref in error.problem
    assert error.path == str(path.absolute())
    jsonschema.validate(error.to_data(), ERROR_SCHEMA)


@pytest.mark.parametrize("kind", ["local", "memory"])
def test_reading_a_reference_not_in_the_store_fails_naming_the_reference(
    tmp_path: Path, kind: str
) -> None:
    store = _stores(tmp_path)[0 if kind == "local" else 1]
    ref = reference(b"never stored")
    with pytest.raises(TroupeError) as caught:
        store.read(ref)
    error = caught.value
    assert error.code == "artifact.missing"
    assert ref in error.problem
    assert "isn't in this store" in error.problem
    if kind == "local":
        assert error.path == str(
            LocalArtifactStore(tmp_path / "artifacts").path_for(ref).absolute()
        )
    jsonschema.validate(error.to_data(), ERROR_SCHEMA)


@pytest.mark.parametrize("bad", ["sha256:ABC", "md5:" + "0" * 32, "sha256:" + "0" * 63, ""])
def test_a_malformed_reference_is_refused(tmp_path: Path, bad: str) -> None:
    for store in _stores(tmp_path):
        with pytest.raises(ValueError, match="not an artifact reference"):
            store.read(bad)


def test_a_store_that_cannot_be_written_reports_the_path(tmp_path: Path) -> None:
    blocker = tmp_path / "artifacts"
    blocker.write_bytes(b"a file where the store's directory should be")
    with pytest.raises(TroupeError) as caught:
        LocalArtifactStore(blocker).put(b"x")
    assert caught.value.code == "artifact.write-failed"
    assert caught.value.path == str(blocker.absolute())
    jsonschema.validate(caught.value.to_data(), ERROR_SCHEMA)


# Requirement: The local store stays out of version control


def test_artifacts_in_a_store_inside_a_git_working_tree_do_not_show_in_git_status(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S607
    (tmp_path / "tracked.txt").write_text("user file\n", encoding="utf-8")
    store = LocalArtifactStore(tmp_path / ".troupe" / "artifacts")
    store.put(b"transcript")
    with store.open_writer() as writer:
        writer.write(b"half")  # a writer in progress leaves a temporary file too
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],  # noqa: S607
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    assert status.splitlines() == ["?? tracked.txt"]
    assert (tmp_path / "tracked.txt").read_text(encoding="utf-8") == "user file\n"


# Requirement: The store is a port


def test_both_stores_satisfy_the_port() -> None:
    stores: list[ArtifactStore] = [LocalArtifactStore(Path("unused")), MemoryArtifactStore()]
    assert len(stores) == 2
