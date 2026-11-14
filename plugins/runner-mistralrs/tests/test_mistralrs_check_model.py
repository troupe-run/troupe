"""The check model the plugin carries is the file its provenance records, under the licences it
records, and the built wheel carries all three (spec: mistralrs-runner, "Tests load no downloaded
model"; in-process-runner design D10; owner, 2026-11-14: check and record its MIT licence)."""

import hashlib
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
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


@pytest.mark.skipif(shutil.which("uv") is None, reason="building the wheel needs uv")
def test_the_built_wheel_carries_the_check_model_its_provenance_and_licence(
    tmp_path: Path,
) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    subprocess.run(
        [uv, "build", "--wheel", "--quiet", "--out-dir", str(tmp_path), str(PLUGIN)],
        check=True,
        timeout=120,
    )
    (wheel,) = tmp_path.glob("troupe_runner_mistralrs-*.whl")
    names = zipfile.ZipFile(wheel).namelist()
    for name in ("stories260K.gguf", "PROVENANCE.md", "LICENSE"):
        assert f"troupe_runner_mistralrs/check_model/{name}" in names
    assert any(
        n.endswith(".dist-info/licenses/src/troupe_runner_mistralrs/check_model/LICENSE")
        for n in names
    )
