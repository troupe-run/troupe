"""The built wheel carries the check model, its provenance and its licence (spec: mistralrs-runner,
"Tests load no downloaded model"; in-process-runner design D10; owner, 2026-11-14: check and
record its MIT licence).

Its tests that stay in their own process are in unit/test_mistralrs_check_model.py."""

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from mistralrs_check_model_shared import PLUGIN


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
