"""The examples in docs/cli/README.md are run as written.

Each `$ troupe ...` line in a console block runs, and its documented output is compared with what
troupe actually prints.
"""

import io
import re
import shlex
from pathlib import Path

import pytest

from troupe.cli import main

pytestmark = pytest.mark.docs  # reads docs/ (scripts/check-paths.toml)

DOC = Path(__file__).resolve().parents[3] / "docs" / "cli" / "README.md"
BLOCK = re.compile(r"```console\n(.*?)```", re.DOTALL)


def _examples() -> list[tuple[str, str]]:
    examples = []
    for block in BLOCK.findall(DOC.read_text(encoding="utf-8")):
        command, _, output = block.partition("\n")
        assert command.startswith("$ troupe"), f"console block must start `$ troupe`: {command}"
        examples.append((command.removeprefix("$ "), output))
    return examples


def test_the_cli_docs_contain_examples() -> None:
    assert len(_examples()) >= 3


@pytest.mark.parametrize(("command", "documented"), _examples())
def test_documented_command_prints_what_the_docs_show(command: str, documented: str) -> None:
    stdout, stderr = io.StringIO(), io.StringIO()
    main(shlex.split(command)[1:], stdout=stdout, stderr=stderr)
    assert stdout.getvalue() + stderr.getvalue() == documented
