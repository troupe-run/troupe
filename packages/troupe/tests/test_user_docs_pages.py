"""What single user docs pages say about troupe, checked against troupe (spec: user-docs; user-docs
design D6)."""

import dataclasses
import io
import json
import os
import re
import shlex
import subprocess
import tomllib
from pathlib import Path
from typing import get_args

import pytest
from ruamel.yaml import YAML

import claude_stand_in
import ollama_stand_in
import openai_stand_in
from gitrepo import AUTHOR, Repo, make_repo
from runtesting import ADA
from troupe.cli import init as init_cli
from troupe.cli import main
from troupe.core import defaults, settings
from troupe.core.audition import OLLAMA_AUDITION_MODEL, OPENAI_AUDITION_LIMITS
from troupe.core.client.messages import State
from troupe.core.policy import ALLOW_UNENFORCED_LOCAL_STAGE, Policy, env_name
from troupe.core.runs.aggregate import TOPICS
from userdocs import DOCS, pages, read

pytestmark = pytest.mark.docs  # reads docs/ (scripts/check-paths.toml)

ROOT = Path(__file__).resolve().parents[3]
BLOCK = re.compile(
    r"^```(?P<lang>\w+)(?P<meta>[^\n]*)\n(?P<body>.*?)^```", re.MULTILINE | re.DOTALL
)


def blocks_in(text: str) -> list[tuple[str, str, str]]:
    """Each fenced block in ``text``: its language, its meta (such as ``title="x"``) and text."""
    return [
        (m.group("lang"), m.group("meta").strip(), m.group("body")) for m in BLOCK.finditer(text)
    ]


def blocks(page: str) -> list[tuple[str, str, str]]:
    """Each fenced block in a page."""
    return blocks_in((DOCS / page).read_text(encoding="utf-8"))


def cli(*argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


# Your first performance (first-run-walkthrough design D1-D5).

PAGE = "opening-night/first-performance.md"
OFFLINE = "Try it offline, with no account"
LOCAL = "Try it with a model on your own machine"
OPENAI = "Try it on OpenAI"
OWN = "Define your own actor"
NOTICE = "Changes the run won't see"
ALLOW = "Allow the local stage, once"
DIRECTION = "Write NOTES.md: what this code is for, in a few lines"
EXAMPLE_COUNT = "1 path(s)"
EXAMPLE_COMMIT = "3f9c2a1b7d4e"
"""The count and commit the page's copy of the uncommitted-changes notice names, each read as the
run's own."""

WALKTHROUGH = [
    "troupe init --audition",
    "troupe config set actors.lead.character=@character.md",
    "git add .troupe",
    "git commit -m 'Add a troupe theatre'",
    "export TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true",
    f'troupe perform lead --direction "{DIRECTION}"',
    "troupe diff <run>",
    "troupe accept <run>",
    "troupe status",
    "troupe logs <run>",
]
OFFLINE_WALKTHROUGH = [
    "mkdir troupe-offline",
    "cd troupe-offline",
    "git init",
    "troupe init --audition --runner scripted",
    "git add .troupe",
    "git commit -m 'Add a troupe theatre'",
    "troupe perform lead",
]
LOCAL_WALKTHROUGH = [
    "ollama pull qwen3.5:4b",
    "mkdir troupe-local",
    "cd troupe-local",
    "git init",
    "troupe init --audition --runner ollama",
    "git add .troupe",
    "git commit -m 'Add a troupe theatre'",
    "troupe perform lead",
]
OPENAI_WALKTHROUGH = [
    "mkdir troupe-openai",
    "cd troupe-openai",
    "git init",
    "troupe init --audition --runner openai",
    "git add .troupe",
    "git commit -m 'Add a troupe theatre'",
    "troupe perform lead",
]
OWN_ACTOR = [
    "troupe config set actors.reviewer.runner=claude-code actors.reviewer.options=@claude.json "
    "actors.reviewer.character=@reviewer.md 'actors.reviewer.expect=[]' "
    "'actors.reviewer.effects.write=[\"REVIEW.md\"]'",
    "git add .troupe",
    "git commit -m 'Add the reviewer actor'",
    'troupe perform reviewer --direction "Review the last commit, and write what you found in '
    'REVIEW.md"',
]


def sh_lines(text: str) -> list[str]:
    """Every line of every sh block in ``text``, in order: the commands a reader runs."""
    return [line for lang, _, body in blocks_in(text) if lang == "sh" for line in body.splitlines()]


def walkthrough() -> str:
    """The page up to its offline section: the Claude Code walkthrough."""
    text = (DOCS / PAGE).read_text(encoding="utf-8")
    return text.split(f"\n## {OFFLINE}\n", 1)[0]


def titled(text: str, title: str) -> str:
    """The body of the one block in ``text`` titled ``title``."""
    (body,) = [body for _, meta, body in blocks_in(text) if meta == f'title="{title}"']
    return body


def git(*args: str) -> None:
    """git in the working directory, as a reader runs it, with the test author as their identity:
    the isolated HOME has none, and only macOS's git makes one up from the host's name."""
    subprocess.run(
        ["git", *args],  # noqa: S607 - git from PATH
        env={**os.environ, **AUTHOR},
        check=True,
        capture_output=True,
    )


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    """The reader's own git repository, with a commit and no theatre, as the working directory,
    with the policy unset."""
    made = make_repo(tmp_path)
    for name, value in {**made.env, **ADA}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(env_name(ALLOW_UNENFORCED_LOCAL_STAGE), raising=False)
    monkeypatch.chdir(made.path)
    (made.path / "README.md").write_text("# my-app\n", encoding="utf-8")
    made.commit_all("Start my-app")
    return made


def stand_in_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write: str) -> None:
    """A stand-in claude first on PATH, writing ``write`` (``path=content``) when it runs. The
    content has no newline: the Windows shim, a .cmd file, can't carry one, and the stand-in
    writes text, which is CRLF there."""
    bin_dir = tmp_path / "bin"
    claude_stand_in.install(
        bin_dir, fixture=claude_stand_in.fixture("success-with-tools"), write=write
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def run_line(line: str, monkeypatch: pytest.MonkeyPatch) -> tuple[int, str, str]:
    """Run one of the page's sh lines as a reader would: troupe in process, git as git, and an
    export as the variable it sets."""
    if line.startswith("export "):
        name, _, value = line.removeprefix("export ").partition("=")
        monkeypatch.setenv(name, value)
        return 0, "", ""
    program, *args = shlex.split(line)
    if program == "git":
        git(*args)
        return 0, "", ""
    assert program == "troupe", line
    return cli(*args)


def perform_walkthrough(monkeypatch: pytest.MonkeyPatch, lines: list[str]) -> tuple[int, str, str]:
    """The walkthrough's lines up to and including its perform, the page's character written
    first; perform's result."""
    # Bytes, so the text is the page's on every platform: write_text writes CRLF on Windows.
    (Path.cwd() / "character.md").write_bytes(titled(walkthrough(), "character.md").encode())
    perform = next(n for n, line in enumerate(lines) if line.startswith("troupe perform"))
    for line in lines[:perform]:
        code, _, err = run_line(line, monkeypatch)
        assert code == 0, (line, err)
    return run_line(lines[perform], monkeypatch)


def test_the_claude_code_walkthrough_runs_as_written_with_a_stand_in_claude(
    project: Repo, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lines = sh_lines(walkthrough())
    assert lines == WALKTHROUGH
    stand_in_claude(tmp_path, monkeypatch, write="NOTES.md=my-app is an app.")
    code, out, err = perform_walkthrough(monkeypatch, lines)
    assert code == 0, err
    run_id = out.split()[1]
    assert out == f"run {run_id} succeeded\n"
    code, out, _ = cli("config", "get", "actors.lead.character")
    assert out.removesuffix("\n") == titled(walkthrough(), "character.md")
    assert not (project.path / "NOTES.md").exists()  # it's in the run's worktree

    code, out, err = run_line(lines[6].replace("<run>", run_id[:8]), monkeypatch)
    assert code == 0, err
    assert "+my-app is an app." in out
    code, _, err = run_line(lines[7].replace("<run>", run_id[:8]), monkeypatch)
    assert code == 0, err
    assert (project.path / "NOTES.md").read_bytes() == b"my-app is an app."
    code, out, _ = run_line(lines[8], monkeypatch)
    assert code == 0
    assert run_id[:8] in out
    code, out, _ = run_line(lines[9].replace("<run>", run_id[:8]), monkeypatch)
    assert code == 0
    assert out.endswith(
        f"run {run_id}: succeeded\n  audit: every change the run made was declared\n"
    ), out


def test_the_walkthroughs_commit_and_allow_lines_are_the_ones_init_prints(
    project: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(init_cli, "SHELL", init_cli.POSIX)  # the page's sh lines
    code, out, err = cli("init", "--audition")
    assert code == 0, err
    printed = [
        re.sub(r"^(\d+\.)? +", "", line)
        for line in out.split("\nNext:\n", 1)[1].splitlines()
        if not line.lstrip().startswith("#")
    ]
    lines = sh_lines(walkthrough())
    assert lines[2:5] == printed[:3]
    assert printed[3].startswith("troupe perform lead --direction ")
    # The page's own direction differs from init's example on purpose: it's the reader's.
    assert lines[5] != printed[3]


def test_the_uncommitted_changes_notice_the_page_shows_is_the_one_perform_writes(
    project: Repo, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (shown,) = [body for lang, _, body in blocks_in(section(PAGE, NOTICE)) if lang == "text"]
    assert shown.startswith(f"troupe: {EXAMPLE_COUNT} differ from HEAD ({EXAMPLE_COMMIT})")
    pattern = (
        re.escape(shown.strip())
        .replace(re.escape(EXAMPLE_COUNT), r"\d+ path\(s\)")
        .replace(EXAMPLE_COMMIT, "[0-9a-f]{12}")
    )
    stand_in_claude(tmp_path, monkeypatch, write="NOTES.md=notes")
    # character.md isn't committed by the page's git add .troupe, as the page says. A change of
    # the reader's own makes 2 paths, so the page's count is read as the run's own, not matched.
    (project.path / "README.md").write_text("# my-app, changed\n", encoding="utf-8")
    code, _, err = perform_walkthrough(monkeypatch, sh_lines(walkthrough()))
    assert code == 0, err
    assert "troupe: 2 path(s) differ from HEAD" in err
    assert re.search(pattern, err), err


def test_the_allow_section_names_the_shell_profiles_and_both_lines(
    project: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = section(PAGE, ALLOW)
    for named in ("~/.zshrc", "~/.bashrc", "$PROFILE", "every theatre"):
        assert named in text
    variable = env_name(ALLOW_UNENFORCED_LOCAL_STAGE)
    assert sh_lines(text) == [init_cli.POSIX.allow_line(variable, "true")]
    powershell = [body.strip() for lang, _, body in blocks_in(text) if lang == "powershell"]
    assert powershell == [init_cli.POWERSHELL.allow_line(variable, "true")]


def test_the_walkthroughs_perform_is_refused_until_the_policy_is_set(
    project: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = [line for line in sh_lines(walkthrough()) if not line.startswith("export ")]
    code, out, err = perform_walkthrough(monkeypatch, lines)
    assert code == 1
    assert out == ""
    assert f"{env_name(ALLOW_UNENFORCED_LOCAL_STAGE)}=true" in err


def test_the_offline_walkthrough_runs_as_written_with_no_claude(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made = make_repo(tmp_path)  # for its HOME and git identity: the reader starts elsewhere
    for name, value in {**made.env, **ADA}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(env_name(ALLOW_UNENFORCED_LOCAL_STAGE), "true")
    no_claude = [
        entry
        for entry in os.environ["PATH"].split(os.pathsep)
        if not any((Path(entry) / name).exists() for name in ("claude", "claude.exe", "claude.cmd"))
    ]
    monkeypatch.setenv("PATH", os.pathsep.join(no_claude))
    start = tmp_path / "work"
    start.mkdir()
    monkeypatch.chdir(start)
    lines = sh_lines(section(PAGE, OFFLINE))
    assert lines == OFFLINE_WALKTHROUGH
    (Path.cwd() / lines[0].split()[1]).mkdir()
    monkeypatch.chdir(Path.cwd() / lines[1].split()[1])
    for line in lines[2:-1]:
        code, _, err = run_line(line, monkeypatch)
        assert code == 0, (line, err)
    code, out, err = run_line(lines[-1], monkeypatch)
    assert code == 0, err
    assert out == f"run {out.split()[1]} succeeded\n"


def test_the_local_model_walkthrough_runs_as_written_with_a_stand_in_ollama(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A stand-in serves the model the page pulls. The reader's Ollama listens at the built-in
    # ollama runtime's address, which a test can't take, so TROUPE_RUNTIME_OLLAMA_ENDPOINT, the
    # reader's own override, points the runtime at the stand-in.
    made = make_repo(tmp_path)
    for name, value in {**made.env, **ADA}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(env_name(ALLOW_UNENFORCED_LOCAL_STAGE), "true")
    lines = sh_lines(section(PAGE, LOCAL))
    assert lines == LOCAL_WALKTHROUGH
    pull, mkdir, cd, *rest = lines
    model = pull.split()[-1]
    assert model == OLLAMA_AUDITION_MODEL
    start = tmp_path / "work"
    start.mkdir()
    monkeypatch.chdir(start)
    (Path.cwd() / mkdir.split()[1]).mkdir()
    monkeypatch.chdir(Path.cwd() / cd.split()[1])
    fake = ollama_stand_in._fake()
    server = fake.FakeOllama(
        [fake.final("Nothing to change.")],
        fake.Settings(models={model: {"capabilities": ["completion", "tools"]}}),
    ).start()
    monkeypatch.setenv("TROUPE_RUNTIME_OLLAMA_ENDPOINT", server.url)
    try:
        for line in rest[:-1]:
            code, _, err = run_line(line, monkeypatch)
            assert code == 0, (line, err)
        code, out, err = run_line(rest[-1], monkeypatch)
    finally:
        server.stop()
    assert code == 0, err
    assert out == f"run {out.split()[1]} succeeded\n"


def test_the_openai_walkthrough_runs_as_written_with_a_stand_in_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The reader's key is in OPENAI_API_KEY and their runs go to OpenAI. Here the key is made up,
    # and TROUPE_RUNTIME_OPENAI_ENDPOINT, the reader's own override, points the runtime at a
    # stand-in, so nothing reaches OpenAI.
    made = make_repo(tmp_path)
    for name, value in {**made.env, **ADA}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(env_name(ALLOW_UNENFORCED_LOCAL_STAGE), "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-docs-walkthrough-0123456789")
    lines = sh_lines(section(PAGE, OPENAI))
    assert lines == OPENAI_WALKTHROUGH
    mkdir, cd, *rest = lines
    start = tmp_path / "work"
    start.mkdir()
    monkeypatch.chdir(start)
    (Path.cwd() / mkdir.split()[1]).mkdir()
    monkeypatch.chdir(Path.cwd() / cd.split()[1])
    with openai_stand_in.serving([openai_stand_in.text_reply("Nothing to change.")]) as fake:
        monkeypatch.setenv("TROUPE_RUNTIME_OPENAI_ENDPOINT", fake.endpoint)
        for line in rest[:-1]:
            code, _, err = run_line(line, monkeypatch)
            assert code == 0, (line, err)
        code, out, err = run_line(rest[-1], monkeypatch)
        assert [r.headers["authorization"] for r in fake.requests] == [
            "Bearer sk-docs-walkthrough-0123456789"
        ]
    assert code == 0, err
    assert out == f"run {out.split()[1]} succeeded\n"


def test_the_openai_section_states_the_auditions_limits_as_the_code_does() -> None:
    text = section(PAGE, OPENAI)
    limits = OPENAI_AUDITION_LIMITS
    assert (
        f"a run stops after {limits['maxTurns']} requests, or once it has used "
        f"{limits['maxTotalTokens']:,} tokens" in " ".join(text.split())
    )
    assert "OPENAI_API_KEY" in text


def test_the_local_model_section_states_the_ollama_the_runner_requires() -> None:
    text = section(PAGE, LOCAL)
    assert "Ollama 0.12.6 or later" in text
    assert "16384 tokens" in text


def test_defining_your_own_actor_runs_as_written_with_a_stand_in_claude(
    project: Repo, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    text = section(PAGE, OWN)
    options = titled(text, "claude.json")
    assert set(json.loads(options)) == {"allowedTools", "maxBudgetUsd"}  # edits come from effects
    (project.path / "claude.json").write_text(options, encoding="utf-8")
    # Bytes, so the text is the page's on every platform: write_text writes CRLF on Windows.
    (project.path / "reviewer.md").write_bytes(titled(text, "reviewer.md").encode())
    lines = sh_lines(text)
    assert lines == OWN_ACTOR
    code, _, err = cli("init")
    assert code == 0, err
    stand_in_claude(tmp_path, monkeypatch, write="REVIEW.md=fine")
    monkeypatch.setenv(env_name(ALLOW_UNENFORCED_LOCAL_STAGE), "true")
    for line in lines[:-1]:
        code, _, err = run_line(line, monkeypatch)
        assert code == 0, (line, err)
    code, out, _ = cli("config", "get", "actors.reviewer.character")
    assert out.removesuffix("\n") == titled(text, "reviewer.md")
    code, out, err = run_line(lines[-1], monkeypatch)
    assert code == 0, err
    assert out == f"run {out.split()[1]} succeeded\n"


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
    assert rows == _defaults(Policy)
    assert env_name(ALLOW_UNENFORCED_LOCAL_STAGE) in policy


def _defaults(seam: type) -> dict[str, str]:
    """Each setting a seam's dataclass reads, and its default as the docs write it."""
    return {
        field.name: str(getattr(defaults, field.name.upper())).lower()
        for field in dataclasses.fields(seam)
    }


def test_the_runs_page_gives_each_settings_default_and_variable_as_the_code_does() -> None:
    page = section(RUNS, "Settings")
    rows = dict(re.findall(r"^\| `([a-z_]+)` \| `([a-z]+)` \|", page, re.MULTILINE))
    assert rows == _defaults(settings.Settings)
    assert settings.env_name(settings.MARK_MERGES_RESOLVED) in page
    assert "`settings.invalid-value`" in page


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


# Point actors at a service (runtimes design; spec: runtimes).

RUNTIMES_PAGE = "stagecraft/runtimes.md"


def test_the_runtimes_pages_commands_run_as_written_and_show_what_it_says(
    project: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert cli("init")[0] == 0  # the page is for a theatre you have
    text = (DOCS / RUNTIMES_PAGE).read_text(encoding="utf-8")
    lines = sh_lines(text)
    assert lines[0] == "troupe config get --resolved runtimes.openai"
    code, out, err = run_line(lines[0], monkeypatch)
    assert code == 0, err
    shown = next(body for lang, _, body in blocks_in(text) if lang == "text")
    assert out == shown
    outputs: dict[str, str] = {}
    for line in lines[1:]:
        code, out, err = run_line(line, monkeypatch)
        assert code == 0, (line, err)
        outputs[line] = out
    office = "troupe config get --resolved runtimes.office-llm"
    assert (
        "runtime office-llm\n  endpoint: https://llm.example.com/v1 (from theatre)"
        in (outputs[office])
    )
    written = (project.path / ".troupe" / "runtimes" / "openai.yaml").read_text(encoding="utf-8")
    assert "model: gpt-4.1-mini" in written
    assert "env: MY_OPENAI_KEY" in written
    prices = YAML(typ="safe", pure=True).load(written)["prices"]
    assert sorted(prices) == ["gpt-4.1", "gpt-5-mini"]  # one set in brackets, beside the other
    assert prices["gpt-4.1"] == {"input": 2, "cacheRead": 0.5, "cacheWrite": 0, "output": 8}


def test_the_runtimes_page_gives_the_built_in_runtimes_as_the_code_does() -> None:
    text = section(RUNTIMES_PAGE, "The runtimes troupe knows")
    rows = re.findall(r"^\| `([a-z-]+)` \| `([^`]+)` \| (?:`([A-Z_]+)`|none) \|$", text, re.M)
    documented = {name: (endpoint, env or None) for name, endpoint, env in rows}
    built_in: dict[str, tuple[str, object]] = {}
    for name, runtime in defaults.RUNTIMES.items():
        credential = runtime.get("credential")
        env = credential.get("env") if isinstance(credential, dict) else None
        built_in[name] = (str(runtime["endpoint"]), env)
    assert documented == built_in


def test_the_runtimes_page_gives_the_shortest_key_as_the_code_does() -> None:
    assert f"a key under {defaults.CREDENTIAL_MIN_BYTES} bytes is refused" in (
        DOCS / RUNTIMES_PAGE
    ).read_text(encoding="utf-8")
