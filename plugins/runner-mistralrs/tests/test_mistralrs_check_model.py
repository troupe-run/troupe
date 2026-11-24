"""The check model the plugin carries is the file its provenance records, under the two MIT licences
it records (spec: mistralrs-runner, "Tests load no downloaded model"; in-process-runner design
D10; owner, 2026-11-14: check and record its MIT licence).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_mistralrs_check_model_integration.py."""

import hashlib
import re

from mistralrs_check_model_shared import PLUGIN

CHECK_MODEL = PLUGIN / "src" / "troupe_runner_mistralrs" / "check_model"


def test_the_check_models_sha256_is_the_one_its_provenance_records() -> None:
    provenance = (CHECK_MODEL / "PROVENANCE.md").read_text(encoding="utf-8")
    recorded = re.search(r"\| SHA-256 \| `([0-9a-f]{64})` \|", provenance)
    assert recorded is not None
    data = (CHECK_MODEL / "stories260K.gguf").read_bytes()
    assert hashlib.sha256(data).hexdigest() == recorded.group(1)
    assert data[:4] == b"GGUF"
    assert f"| Size | {len(data):,} bytes |" in provenance


def test_the_check_models_licences_are_both_mit_and_both_recorded() -> None:
    licence = (CHECK_MODEL / "LICENSE").read_text(encoding="utf-8")
    assert licence.count("MIT License") == 2
    assert licence.count("Permission is hereby granted, free of charge") == 2
    assert "karpathy/tinyllamas" in licence
    assert "ggml-org/models" in licence
    provenance = (CHECK_MODEL / "PROVENANCE.md").read_text(encoding="utf-8")
    assert provenance.count(", MIT |") == 2
