"""Real git repositories for tests, isolated from the machine's own git configuration.

Each repository gets its own HOME, so the user's global config, hooks and credentials never leak
into a test, and a test can set a global config of its own. Commits use a fixed author.

Loaded as a pytest plugin too (``-p gitrepo`` in pyproject.toml's addopts). Under pytest, each
test process builds a repository shape once, as a template, and every test that asks for that shape
gets a copy of it, made to look to git like a fresh build (theatre-template-and-guard-xdist design
D1-D3). Outside pytest (a child process a test starts), every repository is built from scratch.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from functools import cache
from pathlib import Path

import pytest

AUTHOR = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "author@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "author@example.com",
}


def past_the_racy_window() -> int:
    """A wall clock an hour ahead, for a GitAdapter's ``now``: no file looks recently changed, so
    no read is racy and the cache rests on the token's stats alone (cache-vcs-state design D4)."""
    return time.time_ns() + 3600 * 1_000_000_000


def isolated_environment(home: Path) -> dict[str, str]:
    """An environment for git with ``home`` as its home, and nothing of this machine's config."""
    home.mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    if sys.platform == "win32":
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return env


class Repo:
    """A git repository at ``path``, driven with an isolated environment."""

    def __init__(self, path: Path, env: dict[str, str]) -> None:
        self.path = path
        self.env = env

    def git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],  # noqa: S607 - git from the test environment's PATH
            cwd=self.path,
            env={**self.env, **AUTHOR},
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            message = completed.stderr.decode("utf-8", "replace")
            raise AssertionError(f"git {' '.join(args)} failed: {message}")
        return completed.stdout.decode("utf-8")

    def write(self, relative: str, text: str) -> Path:
        path = self.path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def commit_all(self, message: str = "commit") -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD").strip()


REFTABLE_NEEDS = "reftable needs git >= 2.45 (git init --ref-format=reftable)"


@cache
def reftable_supported() -> bool:
    with tempfile.TemporaryDirectory() as scratch:
        completed = subprocess.run(
            ["git", "init", "-q", "--ref-format=reftable", scratch],  # noqa: S607
            capture_output=True,
            check=False,
        )
    return completed.returncode == 0


def require_reftable() -> None:
    """Skip when the installed git can't make a reftable repository, but fail in CI, so CI can't
    lose the reftable cases quietly (cache-vcs-state design D7)."""
    if reftable_supported():
        return
    if os.environ.get("CI"):
        pytest.fail(f"{REFTABLE_NEEDS}; CI must run the reftable cases, not skip them")
    pytest.skip(REFTABLE_NEEDS)


COUNTS_VARIABLE = "TROUPE_TEST_THEATRE_COUNTS"
"""Names an existing directory to write each test process's build and copy counts into, as
``theatres-<pid>.json``, for measuring the templates (design D5). Unset, nothing is written."""

_factory: pytest.TempPathFactory | None = None
"""This process's pytest temp factory while a session runs; None otherwise (outside pytest)."""
_templates: Path | None = None
"""Where this process keeps its templates: made under the base temp when the first is built."""
_built: dict[tuple[object, ...], Path] = {}
"""Each template this process has built, by the key of the shape it holds."""
_counts = {"templates": 0, "copies": 0, "fresh": 0}


def _counts_directory() -> Path | None:
    """The directory ``COUNTS_VARIABLE`` names, or None when it's unset. Set to anything but an
    existing directory, it's refused: a typo would otherwise measure nothing, silently."""
    value = os.environ.get(COUNTS_VARIABLE)
    if value is None:
        return None
    if not value or not Path(value).is_dir():
        raise pytest.UsageError(
            f"{COUNTS_VARIABLE} is {value!r}, which isn't an existing directory. Set it to the "
            "directory to write each test process's theatre counts into, or unset it."
        )
    return Path(value)


def counts() -> dict[str, int]:
    """How many templates this process has built, copies it has made, and fresh builds."""
    return dict(_counts)


def pytest_configure(config: pytest.Config) -> None:
    _counts_directory()


def pytest_sessionfinish(session: pytest.Session) -> None:
    directory = _counts_directory()
    if directory is None or not any(_counts.values()):
        return  # a process that built and copied nothing (xdist's controller) writes nothing
    target = directory / f"theatres-{os.getpid()}.json"
    target.write_text(json.dumps(_counts, sort_keys=True) + "\n", encoding="utf-8")


@pytest.fixture(scope="session", autouse=True)
def theatre_templates(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Keep this process's templates under pytest's base temp (design D2): each xdist worker has its
    own session and base temp, so it builds its own, and a fresh ``--basetemp`` means fresh ones."""
    global _factory, _templates
    _factory = tmp_path_factory
    try:
        yield
    finally:
        _factory = _templates = None
        _built.clear()


def _template_directory() -> Path:
    """The directory for this process's templates, made the first time a template is built. Not
    before: making pytest's base temp registers a cleanup that, at exit, deletes older runs'
    directories, and a session that builds no repository (a child pytest a test starts) mustn't
    pay for that. Old full runs' directories can hold gigabytes of repositories."""
    global _templates
    if _templates is None:
        assert _factory is not None, "only called while a pytest session runs"
        _templates = _factory.mktemp("theatre-templates")
    return _templates


def from_template(
    root: Path, name: str, key: tuple[object, ...], build: Callable[[Path, str], Repo]
) -> Repo:
    """A repository at ``root / name`` with its own empty HOME at ``root / (name + '-home')``,
    copied from the template this process built for ``key`` with ``build(root, name)``, which is
    built first if this is its first use. Outside a pytest session, ``build`` makes it directly.

    The copy's files get new times, as a fresh build's files have, and its index, if it has one, is
    refreshed so its stat data matches the copied files, as after a fresh ``add`` (design D3). A
    copy is never given the template's path, so no test can change the template."""
    if _factory is None:
        _counts["fresh"] += 1
        return build(root, name)
    template = _built.get(key)
    if template is None:
        built = build(Path(tempfile.mkdtemp(dir=_template_directory())), "theatre")
        template = _built[key] = built.path
        _counts["templates"] += 1
    path = root / name
    shutil.copytree(template, path, symlinks=True, copy_function=shutil.copy)
    repo = Repo(path, isolated_environment(root / f"{name}-home"))
    if (path / ".git" / "index").exists():
        # Not -q: a file whose content no longer matches the index (a template changed by mistake)
        # makes --refresh exit 1, so every copy of it fails here, naming the file.
        repo.git("update-index", "--refresh")
    _counts["copies"] += 1
    return repo


def make_repo(
    root: Path,
    name: str = "theatre",
    branch: str = "main",
    refs: str = "files",
    *,
    fresh: bool = False,
) -> Repo:
    """A new repository at ``root / name``, with its own HOME at ``root / (name + '-home')``,
    storing its refs as ``refs`` (``files`` or ``reftable``). It's a copy of this process's
    template for the branch and ref format, unless ``fresh``: a test that depends on a fresh
    ``git init`` (object and file times, the index's stat data, the racy window) asks for one, and
    says which (design D4)."""
    if refs == "reftable":
        require_reftable()
    if fresh:
        _counts["fresh"] += 1
        return _init(root, name, branch, refs)
    return from_template(
        root, name, ("make_repo", branch, refs), lambda at, as_: _init(at, as_, branch, refs)
    )


def _init(root: Path, name: str, branch: str, refs: str) -> Repo:
    path = root / name
    path.mkdir(parents=True)
    repo = Repo(path, isolated_environment(root / f"{name}-home"))
    # Only reftable is named, so a git too old to know --ref-format still makes a files repository.
    repo.git("init", "-q", "-b", branch, *([f"--ref-format={refs}"] if refs != "files" else []))
    return repo


def clone(repo: Repo, root: Path, name: str) -> Repo:
    """A clone of ``repo`` at ``root / name``, sharing its isolated environment."""
    path = root / name
    subprocess.run(
        ["git", "clone", "-q", str(repo.path), str(path)],  # noqa: S607
        env={**repo.env, **AUTHOR},
        check=True,
        capture_output=True,
    )
    return Repo(path, repo.env)
