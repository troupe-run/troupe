"""No gate reads a file under openspec/, so skipping the check for those files skips nothing that
could fail (spec: quality-check; ci-check-scope design D4)."""

import shutil
import subprocess
from pathlib import Path

from conftest import REPO

import check

UNFORMATTED = "# A page\n\n```python\nx  =  1\n```\n"
"""A Python block that ruff format would rewrite (`x = 1`)."""


def test_the_format_gate_fails_a_block_in_docs_and_ignores_the_same_block_in_openspec(
    tmp_path: Path,
) -> None:
    shutil.copy(REPO / "pyproject.toml", tmp_path / "pyproject.toml")
    for page in ("openspec/changes/x/design.md", "docs/x.md"):
        (tmp_path / page).parent.mkdir(parents=True)
        (tmp_path / page).write_text(UNFORMATTED, encoding="utf-8")
    command = dict(check.gates())["ruff format"]

    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=False)

    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "docs/x.md" in output.replace("\\", "/"), output
    assert "openspec" not in output, output
