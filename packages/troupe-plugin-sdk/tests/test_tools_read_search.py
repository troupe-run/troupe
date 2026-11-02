"""Read, Glob and Grep (spec: runner-tools, "Reading and searching", "A failing call is an error
result", "Results are capped by named limits", "The repository's metadata is out of reach";
runner-sdk design D9, D10)."""

from pathlib import Path

from sdk_tools import call, workspace
from troupe_plugin_sdk.defaults import ToolLimits
from troupe_plugin_sdk.tools import Tools

HUNDRED = b"".join(b"line %d\n" % n for n in range(1, 101))


def test_reading_part_of_a_file_returns_those_lines_each_with_its_number(tmp_path: Path) -> None:
    tools = Tools(workspace(tmp_path, {"f.txt": HUNDRED}))
    step = call(tools, "Read", {"file_path": "f.txt", "offset": 10, "limit": 5})
    assert step.output.split("\n") == [
        "10\tline 10",
        "11\tline 11",
        "12\tline 12",
        "13\tline 13",
        "14\tline 14",
        "[Stopped before line 15 of 100: read on with offset 15.]",
    ]


def test_reading_a_whole_small_file_says_nothing_was_left_out(tmp_path: Path) -> None:
    tools = Tools(workspace(tmp_path, {"f.txt": b"one\r\ntwo\n"}))
    assert call(tools, "Read", {"file_path": "f.txt"}).output == "1\tone\n2\ttwo"


def test_reading_more_lines_than_the_line_limit_stops_and_says_where(tmp_path: Path) -> None:
    tools = Tools(workspace(tmp_path, {"f.txt": HUNDRED}), limits=ToolLimits(read_max_lines=3))
    step = call(tools, "Read", {"file_path": "f.txt", "limit": 50})
    assert step.output.split("\n")[-1] == "[Stopped before line 4 of 100: read on with offset 4.]"


def test_a_file_larger_than_the_read_limit_returns_the_lines_that_fit_and_says_to_read_on(
    tmp_path: Path,
) -> None:
    tools = Tools(workspace(tmp_path, {"f.txt": HUNDRED}), limits=ToolLimits(read_max_bytes=40))
    lines = call(tools, "Read", {"file_path": "f.txt"}).output.split("\n")
    assert lines == ["1\tline 1", "2\tline 2", "3\tline 3", "4\tline 4", lines[-1]]
    assert lines[-1] == "[Stopped before line 5 of 100: read on with offset 5.]"


def test_one_line_longer_than_the_read_limit_is_shown_cut_and_says_so(tmp_path: Path) -> None:
    tools = Tools(
        workspace(tmp_path, {"f.txt": b"x" * 100 + b"\n"}), limits=ToolLimits(read_max_bytes=10)
    )
    lines = call(tools, "Read", {"file_path": "f.txt"}).output.split("\n")
    assert lines == ["1\txxxxxxxx", "[Line 1 is longer than 10 bytes; only its start is shown.]"]


def test_reading_a_binary_file_is_an_error_saying_it_isnt_text(tmp_path: Path) -> None:
    step = call(
        Tools(workspace(tmp_path, {"b.bin": b"\xff\xfe\x00"})), "Read", {"file_path": "b.bin"}
    )
    assert step.is_error
    assert "isn't a text file" in step.output


def test_reading_a_missing_file_is_an_error_naming_it(tmp_path: Path) -> None:
    step = call(Tools(workspace(tmp_path)), "Read", {"file_path": "missing.txt"})
    assert step.is_error
    assert step.output == "missing.txt doesn't exist."


def test_reading_past_the_end_is_an_error_giving_the_length(tmp_path: Path) -> None:
    step = call(
        Tools(workspace(tmp_path, {"f.txt": b"a\n"})), "Read", {"file_path": "f.txt", "offset": 5}
    )
    assert step.is_error
    assert "has 1 lines, so offset 5 is past its end" in step.output


def test_reading_an_empty_file_says_so(tmp_path: Path) -> None:
    assert call(
        Tools(workspace(tmp_path, {"e.txt": b""})), "Read", {"file_path": "e.txt"}
    ).output == ("e.txt is empty.")


TREE = {
    "README.md": b"# hi\n",
    "src/main.py": b"def main():\n    pass\n",
    "src/pkg/util.py": b"def helper():\n    def main_inner(): ...\n",
    "src/notes.txt": b"def main in prose\n",
    ".git/config": b"def main secret\n",
    "vendor/.git/HEAD": b"ref\n",
}


def test_glob_returns_the_matching_files_sorted_and_leaves_out_git(tmp_path: Path) -> None:
    tools = Tools(workspace(tmp_path, TREE))
    assert call(tools, "Glob", {"pattern": "**/*.py"}).output == "src/main.py\nsrc/pkg/util.py"
    assert ".git/config" not in call(tools, "Glob", {"pattern": "**"}).output.split("\n")
    assert "vendor/.git/HEAD" in call(tools, "Glob", {"pattern": "**"}).output.split("\n")


def test_glob_matches_its_pattern_relative_to_its_path(tmp_path: Path) -> None:
    tools = Tools(workspace(tmp_path, TREE))
    assert call(tools, "Glob", {"pattern": "*.py", "path": "src"}).output == "src/main.py"


def test_glob_with_no_match_says_so_and_isnt_an_error(tmp_path: Path) -> None:
    step = call(Tools(workspace(tmp_path, TREE)), "Glob", {"pattern": "**/*.rs"})
    assert (step.output, step.is_error) == ("No files match.", False)


def test_a_malformed_glob_pattern_is_an_error_naming_it(tmp_path: Path) -> None:
    step = call(Tools(workspace(tmp_path, TREE)), "Glob", {"pattern": "/etc/*"})
    assert step.is_error
    assert "'/etc/*' is absolute" in step.output


def test_glob_over_its_limit_shows_the_first_paths_and_says_how_many_more(tmp_path: Path) -> None:
    files = {f"f{n:02d}.txt": b"" for n in range(10)}
    tools = Tools(workspace(tmp_path, files), limits=ToolLimits(glob_max_paths=3))
    lines = call(tools, "Glob", {"pattern": "*.txt"}).output.split("\n")
    assert lines == ["f00.txt", "f01.txt", "f02.txt", lines[-1]]
    assert lines[-1] == "[7 more paths not shown: narrow the pattern or the path.]"


def test_grep_with_a_glob_returns_each_matching_line_as_path_line_text(tmp_path: Path) -> None:
    tools = Tools(workspace(tmp_path, TREE))
    step = call(tools, "Grep", {"pattern": "def main", "glob": "**/*.py"})
    assert step.output == "src/main.py:1:def main():\nsrc/pkg/util.py:2:    def main_inner(): ..."


def test_grep_with_no_path_never_returns_a_match_under_git(tmp_path: Path) -> None:
    output = call(Tools(workspace(tmp_path, TREE)), "Grep", {"pattern": "def main"}).output
    assert ".git/" not in output.replace("vendor/.git", "")
    assert "src/notes.txt:1:def main in prose" in output


def test_grep_on_one_file_searches_only_it(tmp_path: Path) -> None:
    tools = Tools(workspace(tmp_path, TREE))
    assert (
        call(tools, "Grep", {"pattern": "def", "path": "src/main.py"}).output
        == "src/main.py:1:def main():"
    )


def test_an_invalid_regular_expression_is_an_error_naming_it(tmp_path: Path) -> None:
    step = call(Tools(workspace(tmp_path, TREE)), "Grep", {"pattern": "(unclosed"})
    assert step.is_error
    assert "'(unclosed' isn't a valid regular expression" in step.output


def test_grep_skips_and_counts_files_that_arent_text_or_are_too_large(tmp_path: Path) -> None:
    files = {"a.txt": b"hit\n", "b.bin": b"hit\xff\n", "c.txt": b"hit\n" + b"x" * 100}
    tools = Tools(workspace(tmp_path, files), limits=ToolLimits(grep_file_max_bytes=50))
    assert call(tools, "Grep", {"pattern": "hit"}).output.split("\n") == [
        "a.txt:1:hit",
        "[1 files over 50 bytes were skipped.]",
        "[1 files that aren't UTF-8 text were skipped.]",
    ]


def test_grep_over_its_match_limit_says_how_many_more(tmp_path: Path) -> None:
    tools = Tools(workspace(tmp_path, {"f.txt": HUNDRED}), limits=ToolLimits(grep_max_matches=2))
    lines = call(tools, "Grep", {"pattern": "line"}).output.split("\n")
    assert lines == ["f.txt:1:line 1", "f.txt:2:line 2", lines[-1]]
    assert lines[-1] == "[98 more matches not shown: narrow the pattern, path or glob.]"


def test_grep_with_no_match_says_so(tmp_path: Path) -> None:
    step = call(Tools(workspace(tmp_path, TREE)), "Grep", {"pattern": "nothing-here"})
    assert (step.output, step.is_error) == ("No matches.", False)


def test_searching_from_a_path_that_doesnt_exist_is_an_error(tmp_path: Path) -> None:
    step = call(Tools(workspace(tmp_path, TREE)), "Glob", {"pattern": "*", "path": "nope"})
    assert step.is_error
    assert step.output == "nope doesn't exist."
