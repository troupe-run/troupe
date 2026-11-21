"""Reading a config file's values (spec: config-hand-edits; hand-edit-sweep design D2, D4)."""

from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from configtesting import TESTER
from troupe.core.config.projection import FIELD_ORDER, RUNTIME_FIELD_ORDER, render
from troupe.core.config.reading import read_values
from troupe.core.errors import TroupeError

CANARY = "canary-7f3a"
TESTER_FIELDS = {k: v for k, v in TESTER.items() if k != "character"}

scalars = st.one_of(
    st.text(max_size=20),
    st.integers(min_value=-(2**53), max_value=2**53),
    st.booleans(),
    st.floats(allow_nan=False, allow_infinity=False, width=64),
)
values = st.one_of(scalars, st.lists(scalars, max_size=4))
keys = st.text(min_size=1, max_size=10)
groups = st.dictionaries(
    keys, st.one_of(values, st.dictionaries(keys, values, max_size=3)), max_size=3
).filter(lambda g: all(not isinstance(v, dict) or v for v in g.values()))
field_values = st.one_of(values, groups.filter(bool))


@settings(max_examples=150, deadline=None)
@given(
    fields=st.dictionaries(st.sampled_from(FIELD_ORDER[1:]), field_values, min_size=1),
    character=st.one_of(st.none(), st.text(min_size=1)),
)
def test_reading_what_render_writes_gives_back_the_actor(
    fields: dict[str, Any], character: str | None
) -> None:
    actor = dict(fields)
    if character is not None:
        actor["character"] = character
    files = render({"actors": {"tester": actor}})
    read = read_values("actors/tester.yaml", files["actors/tester.yaml"])
    assert read.group == ("actors", "tester")
    assert read.owns == "fields"
    assert read.values == fields
    if character is not None:
        md = read_values("actors/tester.md", files["actors/tester.md"])
        assert md.owns == "character"
        assert md.values == {"character": character}


@settings(max_examples=100, deadline=None)
@given(fields=st.dictionaries(st.sampled_from(RUNTIME_FIELD_ORDER[1:]), field_values, min_size=1))
def test_reading_what_render_writes_gives_back_the_runtime(fields: dict[str, Any]) -> None:
    files = render({"runtimes": {"myhost": fields}})
    read = read_values("runtimes/myhost.yaml", files["runtimes/myhost.yaml"])
    assert read.group == ("runtimes", "myhost")
    assert read.values == fields


def test_a_character_is_read_byte_for_byte() -> None:
    text = "Line one\r\nline two\n\n  indented\n"
    read = read_values("actors/tester.md", text.encode())
    assert read.values == {"character": text}


def test_a_file_without_schema_key_is_read() -> None:
    read = read_values("actors/tester.yaml", b"runner: scripted\nexpect: []\n")
    assert read.values == {"runner": "scripted", "expect": []}


def test_yes_is_text_under_yaml_1_2() -> None:
    read = read_values("actors/tester.yaml", b"runner: yes\nexpect: []\n")
    assert read.values["runner"] == "yes"


def _refusal(path: str, data: bytes, where: Path | None = None) -> TroupeError:
    with pytest.raises(TroupeError) as caught:
        read_values(path, data, where)
    error = caught.value
    assert error.code == "config.file-invalid"
    assert f".troupe/{path}" in error.problem
    assert CANARY not in error.problem
    assert CANARY not in error.fix
    assert CANARY not in str(error.details)
    return error


@pytest.mark.parametrize(
    ("path", "data", "rule"),
    [
        ("actors/tester.yaml", b"", "empty"),
        ("actors/tester.md", b"", "empty"),
        ("actors/tester.yaml", b"# only a comment\n", "empty"),
        (
            "runtimes/openai.yaml",
            b"# yaml-language-server: $schema=https://troupe.run/protocol/0/config/runtime.schema.json\n"
            b"$schema: https://troupe.run/protocol/0/config/runtime.schema.json\n",
            "empty",
        ),
        ("actors/tester.md", b"\xff\xfe" + CANARY.encode(), "not-utf-8"),
        ("actors/tester.yaml", b"runner: scripted\n\tmodel: " + CANARY.encode() + b"\n", "syntax"),
        (
            "actors/tester.yaml",
            b"runner: scripted\nrunner: " + CANARY.encode() + b"\n",
            "duplicate-key",
        ),
        ("actors/tester.yaml", b"runner: &r " + CANARY.encode() + b"\nmodel: *r\n", "anchor"),
        ("actors/tester.yaml", b"runner: !!str " + CANARY.encode() + b"\n", "tag"),
        ("actors/tester.yaml", b"options: !!map {a: " + CANARY.encode() + b"}\n", "tag"),
        (
            "actors/tester.yaml",
            b"options:\n  <<: {a: 1}\n  b: " + CANARY.encode() + b"\n",
            "merge-key",
        ),
        ("actors/tester.yaml", b"- " + CANARY.encode() + b"\n", "not-a-mapping"),
        ("actors/tester.yaml", b"options:\n  1: " + CANARY.encode() + b"\n", "key-not-text"),
        ("actors/tester.yaml", b"runner:\nmodel: " + CANARY.encode() + b"\n", "null"),
        ("actors/tester.yaml", b"expect: [a, null]\n", "null"),
        ("actors/tester.yaml", b"model: 2001-12-14\n", "not-json"),
        ("actors/tester.yaml", b"options:\n  t: .nan\n", "not-json"),
        (
            "actors/tester.yaml",
            b"$schema: https://troupe.run/protocol/0/config/runtime.schema.json\nrunner: x\n",
            "schema-url",
        ),
    ],
)
def test_an_invalid_file_is_refused_naming_its_rule(path: str, data: bytes, rule: str) -> None:
    error = _refusal(path, data)
    assert error.details["rule"] == rule
    assert error.details["file"] == f".troupe/{path}"


def test_an_empty_file_says_deleting_it_removes_what_it_held() -> None:
    assert "delete the file to remove the actor tester" in _refusal("actors/tester.yaml", b"").fix
    assert "delete the file to remove the character" in _refusal("actors/tester.md", b"").fix
    assert (
        "delete the file to remove the runtime openai" in _refusal("runtimes/openai.yaml", b"").fix
    )


def test_a_syntax_error_names_its_line_and_column() -> None:
    error = _refusal("actors/tester.yaml", b"runner: scripted\n\tmodel: x\n")
    assert error.details["line"] == 2
    assert error.details["column"] == 1
    assert "(line 2, column 1)" in error.problem


def test_a_refusal_names_the_files_absolute_path(tmp_path: Path) -> None:
    where = tmp_path / ".troupe" / "actors" / "tester.yaml"
    assert _refusal("actors/tester.yaml", b"", where).path == str(where)


def _read_and_check(files: dict[str, bytes]) -> TroupeError:
    from troupe.core.config.reading import refuse_file_problems

    reads = [read_values(path, data) for path, data in files.items()]
    after: dict[str, Any] = {}
    for read in reads:
        kind, name = read.group
        after.setdefault(kind, {}).setdefault(name, {}).update(read.values)
    with pytest.raises(TroupeError) as caught:
        refuse_file_problems(reads, after, Path("/theatre/.troupe"))
    return caught.value


def test_a_misspelt_field_is_refused_naming_the_file() -> None:
    rendered = render({"actors": {"tester": TESTER_FIELDS}})["actors/tester.yaml"]
    error = _read_and_check({"actors/tester.yaml": rendered + b"runnr: scripted\n"})
    assert error.code == "config.file-invalid"
    assert error.details["rule"] == "invalid"
    assert error.details["path"] == ["actors", "tester", "runnr"]
    assert ".troupe/actors/tester.yaml" in error.problem
    assert error.path == "/theatre/.troupe/actors/tester.yaml"


def test_options_the_runner_doesnt_define_are_refused_naming_the_file() -> None:
    error = _read_and_check(
        {
            "actors/tester.yaml": b"runner: scripted\nexpect: []\noptions:\n  script: []\n"
            b"  speed: 3\n"
        }
    )
    assert error.code == "config.file-invalid"
    assert "actors.tester.options" in error.problem
    assert "scripted" in error.problem


def test_a_character_problem_names_the_character_file() -> None:
    from troupe.core.config.reading import refuse_file_problems

    reads = [read_values("actors/tester.md", b"Text.")]
    with pytest.raises(TroupeError) as caught:
        refuse_file_problems(reads, {"actors": {"tester": {"character": "Text."}}})
    assert ".troupe/actors/tester.md" in caught.value.problem


class _Saving:
    """A file whose stamp and bytes change on each read for the first ``changes`` reads."""

    def __init__(self, changes: int) -> None:
        self.changes = changes
        self.reads = 0
        self.stamps = 0

    def stamp(self, path: Path) -> tuple[int, int, int, int]:
        self.stamps += 1
        # Two stamps per attempt: they differ while a save is still going on.
        attempt, after = divmod(self.stamps - 1, 2)
        moving = attempt < self.changes
        return (1, attempt * 2 + (after if moving else 0), 1, 1)

    def read(self, path: Path) -> bytes:
        self.reads += 1
        return b"version %d" % self.reads


def test_a_file_that_changes_once_while_read_is_read_again(tmp_path: Path) -> None:
    from troupe.core.config.reading import read_steady

    saving = _Saving(changes=1)
    data = read_steady(
        tmp_path, "actors/tester.yaml", stamp=saving.stamp, read=saving.read, sleep=lambda _: None
    )
    assert data == b"version 2"
    assert saving.reads == 2


def test_a_file_that_keeps_changing_is_refused(tmp_path: Path) -> None:
    from troupe.core.config.reading import read_steady

    saving = _Saving(changes=99)
    with pytest.raises(TroupeError) as caught:
        read_steady(
            tmp_path,
            "actors/tester.yaml",
            attempts=3,
            stamp=saving.stamp,
            read=saving.read,
            sleep=lambda _: None,
        )
    assert caught.value.code == "config.file-changing"
    assert caught.value.details == {"file": ".troupe/actors/tester.yaml"}
    assert caught.value.path == str(tmp_path / "actors/tester.yaml")
    assert saving.reads == 3


def test_a_steady_real_file_is_read_once(tmp_path: Path) -> None:
    from troupe.core.config.reading import read_steady

    (tmp_path / "actors").mkdir()
    (tmp_path / "actors" / "tester.yaml").write_bytes(b"runner: scripted\n")
    assert read_steady(tmp_path, "actors/tester.yaml") == b"runner: scripted\n"
    assert read_steady(tmp_path, "actors/missing.yaml") is None
