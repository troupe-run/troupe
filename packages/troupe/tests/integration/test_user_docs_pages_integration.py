"""What single user docs pages say about troupe, checked against troupe (spec: user-docs; user-docs
design D6).

Its tests that stay in their own process are in unit/test_user_docs_pages.py."""

import dataclasses
import io
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from ruamel.yaml import YAML

import anthropic_stand_in
import claude_stand_in
import ollama_stand_in
import openai_stand_in
from gitrepo import AUTHOR, Repo, make_repo
from runtesting import ADA, succeeded_run
from troupe.cli import init as init_cli
from troupe.cli import main
from troupe.core import interim
from troupe.core.audition import (
    OLLAMA_AUDITION_MODEL,
)
from troupe.core.exit_codes import ExitCode
from troupe.core.policy import ALLOW_UNENFORCED_LOCAL_STAGE, env_name
from user_docs_pages_shared import (
    ANTHROPIC,
    LOCAL,
    MISTRALRS,
    OPENAI,
    PAGE,
    ROOT,
    RUNTIMES_PAGE,
    blocks_in,
    section,
    sh_lines,
)
from userdocs import DOCS

pytestmark = pytest.mark.docs  # reads docs/ (scripts/check-paths.toml)


def cli(*argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


OFFLINE = "Try it offline, with no account"
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
    "troupe config get actors.lead.character",
    "git add .troupe",
    "git commit -m 'Add a troupe theatre'",
    "export TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true",
    f'troupe perform lead --direction "{DIRECTION}"',
    "troupe diff <run>",
    "troupe approve <run>",
    "troupe config unset actors.lead.approvers",
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
ANTHROPIC_WALKTHROUGH = [
    "mkdir troupe-anthropic",
    "cd troupe-anthropic",
    "git init",
    "troupe init --audition --runner anthropic",
    "git add .troupe",
    "git commit -m 'Add a troupe theatre'",
    "troupe perform lead",
]
MISTRALRS_MODEL = "Qwen3-0.6B-Q8_0.gguf"
MISTRALRS_WALKTHROUGH = [
    f"curl -LO https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/main/{MISTRALRS_MODEL}",
    f'export TROUPE_RUNTIME_MISTRALRS_MODEL="$PWD/{MISTRALRS_MODEL}"',
    "mkdir troupe-mistralrs",
    "cd troupe-mistralrs",
    "git init",
    "troupe init --audition --runner mistralrs",
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


LEAD = ".troupe/actors/lead.md"


def perform_walkthrough(monkeypatch: pytest.MonkeyPatch, lines: list[str]) -> tuple[int, str, str]:
    """The walkthrough's lines up to and including its perform, the page's character written into
    lead.md by hand straight after init, as the page says; perform's result."""
    perform = next(n for n, line in enumerate(lines) if line.startswith("troupe perform"))
    for line in lines[:perform]:
        code, _, err = run_line(line, monkeypatch)
        assert code == 0, (line, err)
        if line.startswith("troupe init"):
            # Bytes, so the text is the page's on every platform: write_text writes CRLF on Windows.
            (Path.cwd() / LEAD).write_bytes(titled(walkthrough(), LEAD).encode())
    return run_line(lines[perform], monkeypatch)


def test_the_claude_code_walkthrough_runs_as_written_with_a_stand_in_claude(
    project: Repo, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lines = sh_lines(walkthrough())
    assert lines == WALKTHROUGH
    stand_in_claude(tmp_path, monkeypatch, write="NOTES.md=my-app is an app.")
    code, out, err = perform_walkthrough(monkeypatch, lines)
    # The audition's actor waits at its gate for director (spec: user-docs, "The first run leads
    # with Claude Code and your own direction").
    assert code == ExitCode.WAITING, err
    assert "waits at its gate for director" in err
    run_id = succeeded_run(out)
    code, out, _ = cli("config", "get", "actors.lead.character")
    assert out.removesuffix("\n") == titled(walkthrough(), LEAD)
    assert not (project.path / "NOTES.md").exists()  # it's in the run's worktree

    code, out, err = run_line(lines[6].replace("<run>", run_id[:8]), monkeypatch)
    assert code == 0, err
    assert "+my-app is an app." in out
    code, _, err = run_line(lines[7].replace("<run>", run_id[:8]), monkeypatch)
    assert code == 0, err
    assert (project.path / "NOTES.md").read_bytes() == b"my-app is an app."

    # Dropping the wait (spec: user-docs, "The first run answers its gate and says how to drop
    # the wait"): the next run, whose changes apply cleanly, is kept without asking.
    code, _, err = run_line(lines[8], monkeypatch)
    assert code == 0, err
    stand_in_claude(tmp_path / "again", monkeypatch, write="LATER.md=later")
    code, out, err = run_line(lines[5], monkeypatch)
    assert code == 0, err
    second = succeeded_run(out)
    assert f"run {second[:8]}'s changes were kept, approved by troupe" in err
    assert (project.path / "LATER.md").read_bytes() == b"later"

    code, out, _ = run_line(lines[9], monkeypatch)
    assert code == 0
    assert run_id[:8] in out
    code, out, _ = run_line(lines[10].replace("<run>", run_id[:8]), monkeypatch)
    assert code == 0
    assert f"run {run_id}: succeeded\n  audit: every change the run made was declared\n" in out
    assert "  approvers: director (actor)\n" in out
    assert re.search(r"  gate: approved by ada@example.com as director at \S+\n$", out), out


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
    # Two changes of the reader's own make 2 paths, so the page's count is read as the run's own,
    # not matched.
    (project.path / "README.md").write_text("# my-app, changed\n", encoding="utf-8")
    (project.path / "TODO.md").write_text("- more\n", encoding="utf-8")
    code, _, err = perform_walkthrough(monkeypatch, sh_lines(walkthrough()))
    assert code == ExitCode.WAITING, err
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
    # The scripted audition writes its file, which waits at its gate for director.
    assert code == ExitCode.WAITING, err
    succeeded_run(out)


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
    succeeded_run(out)


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
    succeeded_run(out)


def test_the_anthropic_walkthrough_runs_as_written_with_a_stand_in_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Spec: user-docs, "The first run has a path for every runner". The reader's key is in
    # ANTHROPIC_API_KEY and their runs go to Claude's API. Here the key is made up, and
    # TROUPE_RUNTIME_ANTHROPIC_ENDPOINT, the reader's own override, points the built-in runtime at
    # a stand-in Messages API service, so nothing reaches Claude's API.
    made = make_repo(tmp_path)
    for name, value in {**made.env, **ADA}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(env_name(ALLOW_UNENFORCED_LOCAL_STAGE), "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", anthropic_stand_in.CANARY)
    lines = sh_lines(section(PAGE, ANTHROPIC))
    assert lines == ANTHROPIC_WALKTHROUGH
    mkdir, cd, *rest = lines
    start = tmp_path / "work"
    start.mkdir()
    monkeypatch.chdir(start)
    (Path.cwd() / mkdir.split()[1]).mkdir()
    monkeypatch.chdir(Path.cwd() / cd.split()[1])
    with anthropic_stand_in.serving([anthropic_stand_in.text_reply("Nothing to change.")]) as fake:
        monkeypatch.setenv("TROUPE_RUNTIME_ANTHROPIC_ENDPOINT", fake.endpoint)
        for line in rest[:-1]:
            code, _, err = run_line(line, monkeypatch)
            assert code == 0, (line, err)
        code, out, err = run_line(rest[-1], monkeypatch)
        assert len(fake.requests) == 1
    assert code == 0, err
    succeeded_run(out)


def test_the_mistralrs_walkthrough_runs_as_written_with_the_engine_stand_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Spec: user-docs, "The first run has a path for every runner". The reader downloads a model
    # and runs it in-process. Here the download is a file with the GGUF signature, and the
    # mistralrs runner runs through its test-only entry point with the engine stand-in, as the
    # conformance test runs it (docs-0-2-0 design D2): the warm-up and the run both reach it. Only
    # on macOS does the warm-up have work to do (the runner answers that there's nothing to warm
    # elsewhere), so only there does init say it prepared the engine.
    made = make_repo(tmp_path)
    for name, value in {**made.env, **ADA}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(env_name(ALLOW_UNENFORCED_LOCAL_STAGE), "true")
    plugin = ROOT / "plugins" / "runner-mistralrs"
    stand_in = (sys.executable, str(plugin / "tests" / "stand_in_runner.py"))
    monkeypatch.setitem(
        interim.RUNNERS,
        "mistralrs",
        dataclasses.replace(interim.RUNNERS["mistralrs"], command=stand_in),
    )
    lines = sh_lines(section(PAGE, MISTRALRS))
    assert lines == MISTRALRS_WALKTHROUGH
    download, export, mkdir, cd, *rest = lines
    start = tmp_path / "work"
    start.mkdir()
    monkeypatch.chdir(start)
    (Path.cwd() / download.rsplit("/", 1)[1]).write_bytes(b"GGUF" + bytes(60))
    name, _, value = export.removeprefix("export ").partition("=")
    monkeypatch.setenv(name, shlex.split(value)[0].replace("$PWD", str(Path.cwd())))
    (Path.cwd() / mkdir.split()[1]).mkdir()
    monkeypatch.chdir(Path.cwd() / cd.split()[1])
    warmed = ""
    for line in rest[:-1]:
        code, _, err = run_line(line, monkeypatch)
        assert code == 0, (line, err)
        if line.startswith("troupe init"):
            warmed = err
    assert "Preparing the mistralrs runner's engine" in warmed
    assert ("Prepared the mistralrs runner's engine in" in warmed) == (sys.platform == "darwin")
    assert "couldn't prepare its engine" not in warmed
    code, out, err = run_line(rest[-1], monkeypatch)
    assert code == 0, err
    succeeded_run(out)


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
    succeeded_run(out)


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
    in_process = "troupe config get --resolved runtimes.mistralrs"
    shown_in_process = [body for lang, _, body in blocks_in(text) if lang == "text"][1]
    assert outputs[in_process] == shown_in_process  # the page's export set the model
    local_openai = project.path / ".troupe" / "runtimes" / "local-openai.yaml"
    assert "endpoint: http://127.0.0.1:8080/v1" in local_openai.read_text(encoding="utf-8")
