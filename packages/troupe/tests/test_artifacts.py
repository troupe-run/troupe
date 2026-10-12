"""Tests for the artifact store port (spec: artifact-store).

The local store is its own package and is tested there, behind the same port.
"""

import hashlib
from pathlib import Path

import jsonschema
import pytest

from runner_schemas import SCHEMAS, load
from troupe.core.artifacts import MemoryArtifactStore, installed_stores, load_store, reference
from troupe.core.errors import TroupeError

ERROR_SCHEMA = load(SCHEMAS / "error.schema.json")


def test_the_memory_store_references_bytes_by_their_sha256() -> None:
    store = MemoryArtifactStore()
    ref = store.put(b"hello\n")
    assert ref == reference(b"hello\n") == "sha256:" + hashlib.sha256(b"hello\n").hexdigest()
    assert store.read(ref) == b"hello\n"


def test_the_memory_store_streams_and_abandons_like_any_store() -> None:
    store = MemoryArtifactStore()
    with store.open_writer() as writer:
        writer.write(b"a")
        writer.write(b"b")
        ref = writer.finish()
    assert store.read(ref) == b"ab"
    abandoned = store.open_writer()
    abandoned.write(b"partial")
    abandoned.abort()
    assert not store.contains(reference(b"partial"))


def test_a_reference_missing_from_the_memory_store_is_an_error_naming_it() -> None:
    with pytest.raises(TroupeError) as caught:
        MemoryArtifactStore().read(reference(b"never"))
    assert caught.value.code == "artifact.missing"
    jsonschema.validate(caught.value.to_data(), ERROR_SCHEMA)


# Requirement: Stores are separately packaged and found by name


def test_the_local_store_is_installed_under_its_name() -> None:
    assert installed_stores()["local"].value == "troupe_artifacts_local:LocalArtifactStore"


def test_asking_for_a_store_no_package_registers_names_it_and_the_installed_stores(
    tmp_path: Path,
) -> None:
    with pytest.raises(TroupeError) as caught:
        load_store("s3", tmp_path)
    error = caught.value
    assert error.code == "artifact.unknown-store"
    assert "'s3'" in error.problem
    assert "local" in error.problem
    assert error.details["installed"] == sorted(installed_stores())
    jsonschema.validate(error.to_data(), ERROR_SCHEMA)
