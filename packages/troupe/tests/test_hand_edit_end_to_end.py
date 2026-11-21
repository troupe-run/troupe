"""Config by hand, end to end through the CLI in a real git theatre (spec: config-hand-edits,
config-files; hand-edit-sweep tasks 7.1)."""

import io
import json
from pathlib import Path

import pytest

from gitrepo import Repo, make_repo
from runtesting import ADA, ALLOW
from troupe.cli import main
from troupe.core.exit_codes import ExitCode

LEAD_YAML = Path(".troupe/actors/lead.yaml")
LEAD_MD = Path(".troupe/actors/lead.md")


def cli(*argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    made = make_repo(tmp_path, "theatre")
    for name, value in {**made.env, **ADA, **ALLOW}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(made.path)
    return made


def _changes(repo: Repo) -> list[dict[str, object]]:
    """Every Config.Changed's state, in the order recorded."""
    found: list[dict[str, object]] = []
    for segment in sorted((repo.path / ".troupe" / "events").glob("*.jsonl")):
        for line in segment.read_bytes().splitlines()[1:]:
            record = json.loads(line)
            if record["topic"].endswith("Config.Changed"):
                found.append(record["state"])
    return found


def test_config_by_hand_from_init_to_sync(repo: Repo) -> None:
    code, _, err = cli("init", "--audition", "--runner", "scripted")
    assert code == ExitCode.OK, err
    repo.commit_all("Add a troupe theatre")
    yaml_text = (repo.path / LEAD_YAML).read_text("utf-8")
    (repo.path / LEAD_YAML).write_text(
        "# lead: tuned by hand\n" + yaml_text + "workspace: theatre\n", encoding="utf-8"
    )
    (repo.path / LEAD_MD).write_bytes(b"You are terse.\n")

    code, _, err = cli("perform", "lead", "--rehearse")
    assert code == ExitCode.WOULD_CHANGE, err
    assert "would record" in err
    assert len(_changes(repo)) == 1  # the audition's: a rehearsal records nothing

    code, _, err = cli("config", "set", "actors.lead.onContextFull=compact")
    assert code == ExitCode.OK, err
    audition, *edits, person = _changes(repo)
    assert sorted(e["lineage"]["vcs"]["source"]["path"] for e in edits) == [  # type: ignore[index]
        str(LEAD_MD).replace("\\", "/"),
        str(LEAD_YAML).replace("\\", "/"),
    ]
    assert all(e["lineage"]["actor"] == {"kind": "unknown"} for e in edits)  # type: ignore[index]
    assert person["lineage"]["actor"]["kind"] == "human"  # type: ignore[index]

    text = (repo.path / LEAD_YAML).read_text("utf-8")
    assert text.startswith("# lead: tuned by hand\n")  # the person's comment, kept
    assert "workspace: theatre" in text
    assert "onContextFull: compact" in text
    assert (repo.path / LEAD_MD).read_bytes() == b"You are terse.\n"

    code, out, err = cli("sync")
    assert code == ExitCode.OK, err
    assert out == "Nothing to do: the config files are what config says.\n"
    code, _, err = cli("sync", "--rehearse")
    assert code == ExitCode.OK, err
    assert len(_changes(repo)) == 1 + len(edits) + 1
    assert audition["lineage"]["actor"]["kind"] == "human"  # type: ignore[index]
