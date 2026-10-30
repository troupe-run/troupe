"""A property of config files across real git merges (spec: config-files; config-projection-
conflicts design D4, task 4.3): for any changes to one actor on two branches, after ``git merge``
and the one troupe command that settles it (``troupe flush``, or the ``troupe config set`` that
resolves config's conflicts), no file is refused, every config file is what the merged config
renders, and every file troupe replaced that wasn't a version it wrote is kept in the artifact
store. With the setting mark_merges_resolved on (drawn per example), every config file git left
unmerged that troupe rewrote is marked resolved with exactly what it wrote, and no other path's
index entry changes (mark-config-resolved task 4.4).

Every example builds two branches of history with real git, which takes several seconds an example
on Windows, so the budget is small: CI's fixed seed still reaches git conflicts, clean merges and
config conflicts with it.
"""

import io
import json
import subprocess
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st

from gitrepo import AUTHOR, Repo
from runtesting import ADA, theatre
from troupe.cli import main
from troupe.core.config.projection import file_hash, render

CHARACTER = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph.\n"
BASE = {
    "actors.tester.runner": "scripted",
    "actors.tester.expect": "[]",
    "actors.tester.options.script.steps": '[{"exit": 0}]',
    "actors.tester.options.script.onCancel": "honour",
    "actors.tester.character": CHARACTER,
}
VALUES = {
    "actors.tester.expect": st.sampled_from(['["out/a.txt"]', '["out/b.txt", "out/c.txt"]', "[]"]),
    "actors.tester.options.script.steps": st.sampled_from(
        ['[{"exit": 1}]', '[{"exit": 2}]', '[{"exit": 0}, {"exit": 3}]']
    ),
    "actors.tester.options.script.onCancel": st.sampled_from(["ignore", "honour-with-result"]),
    "actors.tester.character": st.sampled_from(
        [
            CHARACTER.replace("First", "Edited first"),
            CHARACTER.replace("Third", "Edited third"),
            CHARACTER.replace("Second", "Edited second"),
            "Something else entirely.",
        ]
    ),
}
RESOLVED = {
    "expect": '["out/resolved.txt"]',
    "steps": '[{"exit": 9}]',
    "onCancel": "ignore",
    "character": "Resolved.",
}


def _changes() -> st.SearchStrategy[dict[str, str]]:
    return st.dictionaries(
        st.sampled_from(sorted(VALUES)), st.just(""), min_size=1, max_size=len(VALUES)
    ).flatmap(lambda keys: st.fixed_dictionaries({key: VALUES[key] for key in keys}))


def cli(*argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def _set(values: dict[str, str]) -> None:
    code, _, err = cli("config", "set", *(f"{path}={value}" for path, value in values.items()))
    assert code == 0, err


def _index(repo: Repo) -> dict[str, list[str]]:
    """Each path's index entries (mode, object and stage), as ``ls-files -s`` lists them."""
    entries: dict[str, list[str]] = {}
    for record in repo.git("ls-files", "-s", "-z").split("\0"):
        if record:
            info, _, path = record.partition("\t")
            entries.setdefault(path, []).append(info)
    return entries


def _show(repo: Repo, ref: str, path: str) -> bytes | None:
    shown = subprocess.run(
        ["git", "show", f"{ref}:{path}"],  # noqa: S607 - git from the test's PATH
        cwd=repo.path,
        env=repo.env,
        capture_output=True,
        check=False,
    )
    return shown.stdout if shown.returncode == 0 else None


@settings(max_examples=8, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(feature=_changes(), main_changes=_changes(), marking=st.booleans())
def test_one_command_after_any_merge_leaves_every_file_as_the_merged_config_renders_it(
    monkeypatch: pytest.MonkeyPatch,
    feature: dict[str, str],
    main_changes: dict[str, str],
    marking: bool,
) -> None:
    # Each example's working directory is put back before its directory is removed: Windows can't
    # remove a process's working directory (found in CI, WinError 32).
    with tempfile.TemporaryDirectory() as scratch, monkeypatch.context() as patch:
        repo = theatre(Path(scratch))
        for name, value in {**repo.env, **ADA}.items():
            patch.setenv(name, value)
        if marking:
            patch.setenv("TROUPE_SETTING_MARK_MERGES_RESOLVED", "true")
        patch.chdir(repo.path)
        _set(BASE)
        repo.commit_all("base")
        repo.git("branch", "base")
        repo.git("switch", "-q", "-c", "feature")
        _set(feature)
        repo.commit_all("feature")
        repo.git("switch", "-q", "main")
        _set(main_changes)
        repo.commit_all("main")
        subprocess.run(
            ["git", "merge", "-q", "--no-edit", "feature"],  # noqa: S607
            cwd=repo.path,
            env={**repo.env, **AUTHOR},
            capture_output=True,
            check=False,
        )
        unmerged = repo.git("diff", "--name-only", "--diff-filter=U").split()
        event(f"git left {len(unmerged)} file(s) unmerged")
        actors = repo.path / ".troupe" / "actors"
        before = {p.name: p.read_bytes() for p in actors.iterdir() if p.is_file()}
        index = _index(repo)
        troupes = {
            file_hash(data)
            for name in before
            for ref in ("base", "main", "feature")
            if (data := _show(repo, ref, f".troupe/actors/{name}")) is not None
        }

        _, out, _ = cli("config", "get", "--json")
        conflicts = json.loads(out)["conflicts"]
        resolutions = {
            ".".join(path): RESOLVED[path[-1]]
            for conflict in conflicts
            for path in conflict["paths"]
        }
        event("config conflicts" if resolutions else "config merged cleanly")
        settled = cli("config", "set", *(f"{p}={v}" for p, v in resolutions.items()))
        if not resolutions:
            settled = cli("flush")
        assert settled[0] == 0, settled[2]

        _, out, _ = cli("config", "get", "--json")
        merged = json.loads(out)
        assert merged["conflicts"] == []
        rendered = render(merged["value"])
        on_disk = {f"actors/{p.name}": p.read_bytes() for p in actors.iterdir() if p.is_file()}
        assert on_disk == rendered
        store = repo.path / ".troupe" / "local" / "artifacts" / "sha256"
        for name, data in before.items():
            replaced = on_disk.get(f"actors/{name}") != data
            if replaced and file_hash(data) not in troupes:
                event("a file troupe didn't write was replaced and kept")
                kept = file_hash(data)
                assert (store / kept[7:9] / kept[7:]).read_bytes() == data, name

        after = _index(repo)
        rewritten = {
            f".troupe/{path}"
            for path in rendered.keys() | {f"actors/{name}" for name in before}
            if on_disk.get(path) != before.get(path.removeprefix("actors/"))
        }
        for path in sorted(index.keys() | after.keys()):
            if marking and path in rewritten and path in unmerged:
                event("an unmerged file troupe rewrote was marked resolved")
                data = on_disk.get(path.removeprefix(".troupe/"))
                if data is None:
                    assert path not in after, path
                else:
                    [entry] = after[path]
                    assert entry.endswith(" 0"), path
                    assert _show(repo, "", path) == data, path
            else:
                assert after.get(path) == index.get(path), path
