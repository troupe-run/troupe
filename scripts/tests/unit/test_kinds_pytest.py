"""The kinds plugin's pure parts: a test file's kind from its path, what an audit event reached,
and the test modules a module imports (spec: quality-check; test-split design D3a-D5). The plugin's
behaviour in a real pytest run is in integration/test_kinds_pytest_runs.py."""

import platform
import socket
import subprocess

import pytest

import kinds_pytest

# Made-up packages: a real package path here would read, to the reach check, as reaching it.
SUITES = [
    "packages/example/tests",
    "plugins/runner-example/tests",
    "scripts/tests",
    "scripts/tests/workspace",
]


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("packages/example/tests/unit/test_errors.py", "unit"),
        ("packages/example/tests/integration/test_cli_runs.py", "integration"),
        ("plugins/runner-example/tests/unit/test_example_options.py", "unit"),
        ("scripts/tests/integration/test_flake_hunt.py", "integration"),
        ("scripts/tests/workspace/unit/test_install_docs.py", "unit"),
        ("scripts/tests/workspace/integration/test_install_check.py", "integration"),
    ],
)
def test_a_files_kind_is_the_directory_directly_under_its_suite(path: str, kind: str) -> None:
    assert kinds_pytest.kind_of(path, SUITES) == kind


@pytest.mark.parametrize(
    "path",
    [
        "packages/example/tests/test_new.py",  # directly in the suite
        "packages/example/tests/helpers/test_new.py",  # under another directory
        "packages/example/tests/unit",  # the directory itself
        "scripts/tests/workspace/test_new.py",  # the nested suite's own top level
        "docs/unit/test_new.py",  # under no suite
    ],
)
def test_a_file_in_neither_kinds_directory_has_no_kind(path: str) -> None:
    assert kinds_pytest.kind_of(path, SUITES) is None


def test_the_nested_suite_is_the_one_holding_its_files() -> None:
    assert kinds_pytest.suite_of("scripts/tests/workspace/unit/x.py", SUITES) == (
        "scripts/tests/workspace"
    )
    assert kinds_pytest.suite_of("scripts/tests/unit/x.py", SUITES) == "scripts/tests"


def test_starting_a_process_names_its_program() -> None:
    args = ("/usr/bin/git", ["/usr/bin/git", "status"], None, None)
    assert kinds_pytest.reached("subprocess.Popen", args) == "a process (git)"


@pytest.mark.parametrize(
    "command_line",
    ["python.exe -c pass", r'"C:\Program Files\Python 3.14\python.exe" -c pass', "git status"],
)
def test_a_command_line_already_joined_names_its_program(command_line: str) -> None:
    # On Windows the subprocess.Popen event carries the command line joined into one string.
    program = "git" if command_line.startswith("git") else "python.exe"
    args = (None, command_line, None, None)
    assert kinds_pytest.reached("subprocess.Popen", args) == f"a process ({program})"


def test_popens_own_createprocess_on_windows_isnt_counted_twice() -> None:
    create = _compiled_as(
        subprocess,
        "def _execute_child(reached):\n"
        "    return reached('_winapi.CreateProcess', (None, 'python.exe -c pass'))\n",
    )["_execute_child"]
    assert callable(create)
    assert create(kinds_pytest.reached) is None
    assert kinds_pytest.reached("_winapi.CreateProcess", ()) == "a process (_winapi.CreateProcess)"


@pytest.mark.parametrize(
    "event", ["os.system", "os.posix_spawn", "os.fork", "os.exec", "_winapi.CreateProcess"]
)
def test_other_ways_of_starting_a_process_name_the_event(event: str) -> None:
    assert kinds_pytest.reached(event, ()) == f"a process ({event})"


@pytest.mark.parametrize(
    "event", ["socket.connect", "socket.bind", "socket.sendto", "socket.sendmsg"]
)
def test_a_sockets_connect_bind_or_send_to_an_address_is_a_socket(event: str) -> None:
    assert kinds_pytest.reached(event, (object(), ("127.0.0.1", 0))) == "a socket"


@pytest.mark.parametrize("event", ["open", "socket.getaddrinfo", "import", "os.listdir"])
def test_an_event_no_reach_declares_reaches_nothing(event: str) -> None:
    assert kinds_pytest.reached(event, ()) is None


def test_each_event_belongs_to_one_declared_reach() -> None:
    events = [event for reach in kinds_pytest.OUTSIDE for event in reach.events]
    assert len(events) == len(set(events))
    names = [reach.name for reach in kinds_pytest.OUTSIDE]
    assert len(names) == len(set(names))


@pytest.mark.parametrize(
    ("source", "imported"),
    [
        ("from test_perform import configured\n", ["test_perform"]),
        ("import test_openai_live\n", ["test_openai_live"]),
        ("def test_x():\n    from test_client_messages import ENDED\n", ["test_client_messages"]),
        ("import json\nfrom runtesting import theatre\nimport cli_runs_shared\n", []),
        ("from . import test_x\n", []),  # relative: not how troupe's tests import
    ],
)
def test_the_test_modules_a_module_imports_at_any_depth(source: str, imported: list[str]) -> None:
    assert kinds_pytest.imported_tests(source) == imported


def _compiled_as(module: object, source: str) -> dict[str, object]:
    """Run `source` as if it were part of a standard library module's own file."""
    namespace: dict[str, object] = {}
    exec(compile(source, str(getattr(module, "__file__", "")), "exec"), namespace)  # noqa: S102
    return namespace


@pytest.mark.parametrize("name", ["socketpair", "_fallback_socketpair"])
def test_a_connect_made_inside_socket_socketpair_isnt_counted(name: str) -> None:
    # Where the platform has no native pair (Windows), socket.socketpair is socket.py's
    # _fallback_socketpair, which links its ends through a loopback bind and connect. Linux and
    # macOS make the pair natively, so this is exercised everywhere by running the hook from a
    # function that is, to the frame check, socket.py's own.
    pair = _compiled_as(
        socket, f"def {name}(reached):\n    return reached('socket.connect', (None, None))\n"
    )[name]
    assert callable(pair)
    assert pair(kinds_pytest.reached) is None
    assert kinds_pytest.reached("socket.connect", (None, ("127.0.0.1", 1))) == "a socket"


def test_a_function_named_socketpair_outside_the_standard_library_is_counted() -> None:
    namespace: dict[str, object] = {}
    exec(  # noqa: S102 - our own two lines, compiled under another module's name
        compile(
            "def socketpair(reached):\n    return reached('socket.connect', (None, None))\n",
            "/elsewhere/socket.py",
            "exec",
        ),
        namespace,
    )
    pair = namespace["socketpair"]
    assert callable(pair)
    assert pair(kinds_pytest.reached) == "a socket"


def test_a_process_the_platform_module_starts_isnt_counted() -> None:
    # platform.uname() and platform.architecture() run uname and file; libraries cache the answer
    # (the OpenAI SDK's headers do), so counting them would charge whichever test asked first.
    architecture = _compiled_as(
        platform,
        "def architecture(reached):\n"
        "    return reached('subprocess.Popen', ('file', ['file', '-b', 'python']))\n",
    )["architecture"]
    assert callable(architecture)
    assert architecture(kinds_pytest.reached) is None
    assert kinds_pytest.reached("subprocess.Popen", ("file", ["file"])) == "a process (file)"
