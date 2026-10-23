"""What single user docs pages say about troupe, checked against troupe (spec: user-docs; user-docs
design D6)."""

import io
import json
import re
import shlex
import tomllib
from pathlib import Path
from typing import get_args

import pytest

from gitrepo import Repo
from runtesting import ADA, theatre
from troupe.cli import main
from troupe.core import defaults
from troupe.core.client.messages import State
from troupe.core.policy import ALLOW_UNENFORCED_LOCAL_STAGE, env_name
from troupe.core.runs.aggregate import TOPICS
from userdocs import DOCS, pages, read

pytestmark = pytest.mark.docs  # reads docs/ (scripts/check-paths.toml)

ROOT = Path(__file__).resolve().parents[3]
BLOCK = re.compile(
    r"^```(?P<lang>\w+)(?P<meta>[^\n]*)\n(?P<body>.*?)^```", re.MULTILINE | re.DOTALL
)


def blocks(page: str) -> list[tuple[str, str, str]]:
    """Each fenced block in a page: its language, its meta (such as ``title="x"``) and its text."""
    text = (DOCS / page).read_text(encoding="utf-8")
    return [
        (m.group("lang"), m.group("meta").strip(), m.group("body")) for m in BLOCK.finditer(text)
    ]


def cli(*argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


# Your first performance.


@pytest.fixture
def fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    """A new git theatre as the working directory, with the policy unset, as a reader has it."""
    made = theatre(tmp_path)
    for name, value in {**made.env, **ADA}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE", raising=False)
    monkeypatch.chdir(made.path)
    return made


def test_the_first_performance_runs_as_written_and_writes_its_file(
    fresh: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = "opening-night/first-performance.md"
    (script,) = [body for lang, meta, body in blocks(page) if meta == 'title="hello.json"']
    json.loads(script)  # the reader copies it as it is: it must be JSON
    (fresh.path / "hello.json").write_text(script, encoding="utf-8")
    lines = [line for lang, _, body in blocks(page) if lang == "sh" for line in body.splitlines()]
    assert lines == [
        "troupe config set actors.tester.runner=scripted actors.tester.options=@hello.json "
        "'actors.tester.expect=[\"out/hello.txt\"]'",
        "git add -A",
        'git commit -m "Add the tester actor"',
        "export TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true",
        "troupe perform tester",
        "troupe diff <run>",
        "troupe accept <run>",
        "troupe status",
        "troupe logs <run>",
    ]
    code, _, err = cli(*shlex.split(lines[0])[1:])
    assert code == 0, err
    assert (fresh.path / ".troupe" / "actors" / "tester.yaml").is_file()
    fresh.git(*shlex.split(lines[1])[1:])
    fresh.git(*shlex.split(lines[2])[1:])
    name, _, value = lines[3].removeprefix("export ").partition("=")
    monkeypatch.setenv(name, value)

    code, out, err = cli(*shlex.split(lines[4])[1:])
    assert code == 0, err
    run_id = out.split()[1]
    assert out == f"run {run_id} succeeded\n"
    assert not (fresh.path / "out" / "hello.txt").exists()  # it's in the run's worktree

    code, out, err = cli(*shlex.split(lines[5].replace("<run>", run_id[:8]))[1:])
    assert code == 0, err
    assert "+hello" in out
    code, out, err = cli(*shlex.split(lines[6].replace("<run>", run_id[:8]))[1:])
    assert code == 0, err
    assert (fresh.path / "out" / "hello.txt").read_text(encoding="utf-8") == "hello\n"

    code, out, _ = cli(*shlex.split(lines[7])[1:])
    assert code == 0
    assert run_id[:8] in out
    code, out, _ = cli(*shlex.split(lines[8].replace("<run>", run_id[:8]))[1:])
    assert code == 0
    assert "wrote out/hello.txt" in out


def test_the_first_performance_is_refused_until_the_policy_is_set(fresh: Repo) -> None:
    page = "opening-night/first-performance.md"
    (script,) = [body for _, meta, body in blocks(page) if meta == 'title="hello.json"']
    (fresh.path / "hello.json").write_text(script, encoding="utf-8")
    [define] = [
        line
        for lang, _, body in blocks(page)
        if lang == "sh"
        for line in body.splitlines()
        if line.startswith("troupe config set")
    ]
    assert cli(*shlex.split(define)[1:])[0] == 0
    code, out, err = cli("perform", "tester")
    assert code == 1
    assert out == ""
    assert "TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true" in err


# Performances and runs.


def section(page: str, heading: str) -> str:
    text = (DOCS / page).read_text(encoding="utf-8")
    match = re.search(
        rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    assert match is not None, f"{page} has no section {heading!r}"
    return match.group(1)


RUNS = "the-company/performances-and-runs.md"


def test_the_runs_page_lists_exactly_the_states_a_run_can_be_in() -> None:
    rows = re.findall(r"^\| `([a-z-]+)` \|", section(RUNS, "A run's state"), re.MULTILINE)
    assert set(rows) == set(get_args(State))


def test_the_runs_page_lists_exactly_the_events_a_run_records() -> None:
    named = re.findall(
        r"^- \*\*`(Run\.[A-Za-z]+)`:", section(RUNS, "What a run records"), re.MULTILINE
    )
    assert {f"Run.{name.split('.')[-1]}" for name in TOPICS} == set(named)


def test_the_runs_page_gives_each_policy_settings_default_and_variable_as_the_code_does() -> None:
    policy = section(RUNS, "Policy")
    rows = dict(re.findall(r"^\| `([a-z_]+)` \| `([a-z]+)` \|", policy, re.MULTILINE))
    assert rows == {
        ALLOW_UNENFORCED_LOCAL_STAGE: str(defaults.ALLOW_UNENFORCED_LOCAL_STAGE).lower()
    }
    assert env_name(ALLOW_UNENFORCED_LOCAL_STAGE) in policy


# Lineage.


def test_every_field_the_lineage_page_describes_is_one_the_lineage_schema_defines() -> None:
    schema = json.loads((ROOT / "protocol/schemas/lineage.schema.json").read_text(encoding="utf-8"))
    named = re.findall(
        r"^- \*\*`([a-z]+)`:\*\*",
        section("the-company/lineage.md", "What lineage says"),
        re.MULTILINE,
    )
    assert set(named) == set(schema["properties"])


# Install.


def test_the_install_page_gives_the_python_versions_troupe_declares() -> None:
    declared = tomllib.loads((ROOT / "packages/troupe/pyproject.toml").read_text(encoding="utf-8"))
    bound = re.fullmatch(r">=3\.(\d+),<3\.(\d+)", declared["project"]["requires-python"])
    assert bound is not None
    low, high = int(bound.group(1)), int(bound.group(2)) - 1
    text = (DOCS / "opening-night/install.md").read_text(encoding="utf-8")
    assert f"Python 3.{low} to 3.{high}" in text


# Every page.


def test_no_page_is_still_planned() -> None:
    planned = [
        path.relative_to(DOCS).as_posix()
        for path in pages()
        if read(path).front["status"] == "planned"
    ]
    assert planned == []
