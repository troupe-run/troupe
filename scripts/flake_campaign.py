"""Run the flake-hunt campaign #100 agreed, one hunt after another (spec: flake-hunt; design D11).

Usage: uv run scripts/flake_campaign.py [--docker | --docker-only] [--all] [--workers N|auto]
                                        [--rounds N] [--loads 0,2] [--pythons 3.12,3.13]
                                        [--out DIR] [PATH ...]

For every supported Python version (python_versions.py, which ties the bound to CI's matrix), and
each load, it runs scripts/flake_hunt.py directly, then (with --docker) the same hunts in the Linux
container, or with --docker-only only those. Each direct hunt runs in that version's
.venvs/<version>, as scripts/on.py does, so .venv is never touched. The report, report.md for #100
and campaign.json, is written after every hunt, so a stopped campaign still says what it found.
contributing/flake-hunt.md says how to run it on each platform.
"""

import argparse
import contextlib
import dataclasses
import datetime
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import flake_hunt
import on
import python_versions

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = "scripts/flake_hunt.Dockerfile"
CONTAINER_OUT = "/home/hunter/out"

WORKERS = "auto"
ROUNDS = 10
LOADS = (0, 2)
"""The campaign #100 agreed: 10 rounds, without load and with 2 CPUs busy, in as many workers as
three quarters of the CPUs (flake_hunt.py's --workers auto, resolved by each hunt where it runs,
so a container counts its own CPUs)."""

SELECTION = (
    "packages/troupe/tests/test_platform_*.py",
    "packages/troupe/tests/test_run_host.py",
    "packages/troupe/tests/test_cli_runs.py",
    "packages/troupe-store-text/tests",
    "packages/troupe-vcs-git/tests",
    "plugins/runner-scripted/tests",
)
"""The tests that depend on time, processes, signals or file watching: what #100's hunts ran.
Patterns, so a new platform test file joins without an edit; a test checks each still matches."""

STOP_WAIT_SECONDS = 60.0
"""How long a stopped hunt has to write its summary before the campaign kills it."""
WAIT_SECONDS = 0.5
"""The longest single wait on a hunt: Windows can't interrupt a wait with no timeout."""


class CampaignError(Exception):
    """Something that stops the campaign before it starts, with the fix."""


def supported_pythons(root: Path) -> list[str]:
    """Every supported Python version, from the root's bound, which python_versions.py's check
    keeps equal to CI's matrix."""
    try:
        return python_versions.supported(root)
    except python_versions.BoundError as error:
        raise CampaignError(str(error)) from None


def _workers(text: str) -> str:
    """A number of workers, or auto: checked here, resolved by each hunt where it runs."""
    flake_hunt.parse_workers(text)
    return text


def expand(root: Path, patterns: Sequence[str]) -> list[str]:
    """Each pattern's files and directories under ``root``, as paths relative to it."""
    found: list[str] = []
    for pattern in patterns:
        matches = sorted(path.relative_to(root).as_posix() for path in root.glob(pattern))
        if not matches:
            raise CampaignError(f"the selection pattern {pattern!r} matches nothing under {root}")
        found += matches
    return found


# The plan


@dataclasses.dataclass(frozen=True)
class Hunt:
    python: str
    load: int
    docker: bool

    @property
    def name(self) -> str:
        return f"{'docker' if self.docker else 'direct'}-{self.python}-load{self.load}"


@dataclasses.dataclass(frozen=True)
class Options:
    workers: str
    rounds: int
    loads: tuple[int, ...]
    pythons: tuple[str, ...]
    docker: bool
    selection: tuple[str, ...]
    selection_label: str
    out: Path
    environments: Path
    root: Path
    hunt_root: Path | None = None  # where pytest runs, when not this repository (tests use it)
    direct: bool = True

    def hunts(self) -> list[Hunt]:
        plan: list[Hunt] = []
        if self.direct:
            plan += [Hunt(p, load, False) for p in self.pythons for load in self.loads]
        if self.docker:
            plan += [Hunt(p, load, True) for p in self.pythons for load in self.loads]
        return plan


def _whole(name: str, minimum: int) -> Callable[[str], int]:
    def parse(text: str) -> int:
        try:
            value = int(text, 10)
        except ValueError:
            value = None
        if value is None or value < minimum:
            raise argparse.ArgumentTypeError(
                f"{text!r} isn't allowed: {name} must be a whole number, {minimum} or more"
            )
        return value

    return parse


def _list[T](name: str, item: Callable[[str], T]) -> Callable[[str], tuple[T, ...]]:
    def parse(text: str) -> tuple[T, ...]:
        parts = [part.strip() for part in text.split(",")]
        if not all(parts):
            raise argparse.ArgumentTypeError(f"{text!r} isn't allowed: {name} is a comma list")
        return tuple(item(part) for part in parts)

    return parse


def _version(text: str) -> str:
    if not re.fullmatch(r"\d+\.\d+", text):
        raise argparse.ArgumentTypeError(f"{text!r} isn't a Python version like 3.12")
    return text


def parse_options(argv: Sequence[str]) -> Options:
    parser = argparse.ArgumentParser(
        prog="flake_campaign.py",
        description="Run the agreed flake-hunt campaign (contributing/flake-hunt.md).",
    )
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--docker", action="store_true", help="also hunt in the Linux container")
    where.add_argument(
        "--docker-only", action="store_true", help="hunt only in the Linux container"
    )
    parser.add_argument("--all", action="store_true", help="hunt the whole suite")
    parser.add_argument("--workers", type=_workers, default=WORKERS, help="a number, or auto")
    parser.add_argument("--rounds", type=_whole("--rounds", 1), default=ROUNDS)
    parser.add_argument("--loads", type=_list("--loads", _whole("--loads", 0)), default=LOADS)
    parser.add_argument(
        "--pythons",
        type=_list("--pythons", _version),
        help="instead of every supported version (default: python_versions.py's)",
    )
    parser.add_argument("--out", type=Path, help="where the report goes (default: the temp dir)")
    parser.add_argument(
        "--environments",
        type=Path,
        default=ROOT / on.ENVIRONMENTS,
        help="where each version's environment lives (default: .venvs, as scripts/on.py uses)",
    )
    parser.add_argument(
        "--hunt-root",
        type=Path,
        help="where the direct hunts run pytest (default: this repository)",
    )
    parser.add_argument("paths", nargs="*", help="test paths, instead of the OS-sensitive tests")
    parsed = parser.parse_args(argv)
    if parsed.all and parsed.paths:
        parser.error("--all and test paths can't both be given: --all hunts the whole suite")
    hunt_root = parsed.hunt_root.resolve() if parsed.hunt_root else None
    docker = parsed.docker or parsed.docker_only
    if hunt_root is not None and docker:
        given = "--docker-only" if parsed.docker_only else "--docker"
        parser.error(
            f"--hunt-root and {given} can't both be given: the image hunts this repository"
        )
    tests_root = hunt_root or ROOT
    try:
        pythons = tuple(parsed.pythons or supported_pythons(ROOT))
        if parsed.all:
            selection: tuple[str, ...] = ()
            label = "the whole suite"
        elif parsed.paths:
            for path in parsed.paths:
                if not (tests_root / path.split("::", 1)[0]).exists():
                    raise CampaignError(f"{path!r} doesn't exist under {tests_root}")
            selection, label = tuple(parsed.paths), "the given paths"
        else:
            selection = tuple(expand(ROOT, SELECTION))
            label = "the OS-sensitive tests"
    except CampaignError as error:
        parser.error(str(error))
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    out = parsed.out or Path(tempfile.gettempdir()) / "flake-campaign" / stamp
    return Options(
        workers=parsed.workers,
        rounds=parsed.rounds,
        loads=parsed.loads,
        pythons=pythons,
        docker=docker,
        selection=selection,
        selection_label=label,
        out=out.resolve(),
        environments=parsed.environments.resolve(),
        root=ROOT,
        hunt_root=hunt_root,
        direct=not parsed.docker_only,
    )


# Commands


def environment_python(environment: Path) -> Path:
    if sys.platform == "win32":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def hunt_arguments(options: Options, hunt: Hunt) -> list[str]:
    return [
        "--workers",
        str(options.workers),
        "--rounds",
        str(options.rounds),
        "--load",
        str(hunt.load),
        *options.selection,
    ]


def sync_command(uv: str, hunt: Hunt) -> list[str]:
    return [uv, "sync", "--locked", "--python", hunt.python]


def direct_command(options: Options, hunt: Hunt, out: Path) -> list[str]:
    environment = options.environments / hunt.python
    script = str(options.root / "scripts" / "flake_hunt.py")
    python = str(environment_python(environment))
    where = ["--root", str(options.hunt_root)] if options.hunt_root is not None else []
    return [python, script, "--out", str(out), *where, *hunt_arguments(options, hunt)]


def image(hunt: Hunt) -> str:
    return f"troupe-hunt:{hunt.python}"


def build_command(docker: str, hunt: Hunt) -> list[str]:
    return [
        docker,
        "build",
        "--quiet",
        "--tag",
        image(hunt),
        "--build-arg",
        f"PY={hunt.python}",
        "--file",
        DOCKERFILE,
        "-",
    ]


def container(stamp: str, hunt: Hunt) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", f"flake-campaign-{stamp}-{hunt.name}")


def docker_command(docker: str, options: Options, hunt: Hunt, name: str) -> list[str]:
    return [docker, "run", "--init", "--name", name, image(hunt), *hunt_arguments(options, hunt)]


# Running


@dataclasses.dataclass
class Outcome:
    hunt: Hunt
    status: str  # "clean", "failed", "stopped" or "didn't run"
    exit_code: int | None = None
    summary: dict[str, Any] | None = None
    reason: str = ""

    def record(self) -> dict[str, Any]:
        return {
            "hunt": self.hunt.name,
            "python": self.hunt.python,
            "load": self.hunt.load,
            "docker": self.hunt.docker,
            "status": self.status,
            "exitCode": self.exit_code,
            "reason": self.reason,
            "summary": self.summary,
        }


class Stopped(Exception):  # noqa: N818 - control flow, not an error
    """Ctrl-C (or Ctrl-Break) during a hunt: it has been stopped, and no more should run."""


def _raise_interrupt(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


def wait(process: subprocess.Popen[bytes]) -> int:
    """Wait for a hunt, in short waits. On Ctrl-C the hunt has had it too, and stops itself:
    give it time to write its summary, then raise Stopped."""
    try:
        while (code := process.poll()) is None:
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(WAIT_SECONDS)
        return code
    except KeyboardInterrupt:
        print("\nflake_campaign: stopping after this hunt has written its summary", flush=True)
        deadline = time.monotonic() + STOP_WAIT_SECONDS
        while process.poll() is None and time.monotonic() < deadline:
            with contextlib.suppress(subprocess.TimeoutExpired, KeyboardInterrupt):
                process.wait(WAIT_SECONDS)
        if process.poll() is None:
            process.kill()
            process.wait()
        raise Stopped from None


def read_summary(out: Path) -> dict[str, Any] | None:
    try:
        data: dict[str, Any] = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return data


def outcome_of(hunt: Hunt, code: int, out: Path) -> Outcome:
    summary = read_summary(out)
    if summary is None:
        return Outcome(hunt, "didn't run", code, None, f"the hunt exited {code} with no summary")
    if summary.get("stopped"):
        return Outcome(hunt, "stopped", code, summary)
    return Outcome(hunt, "failed" if summary["roundsFailed"] else "clean", code, summary)


def run_direct(options: Options, hunt: Hunt, uv: str, out: Path) -> Outcome:
    env = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}  # as on.py
    env["UV_PROJECT_ENVIRONMENT"] = str(options.environments / hunt.python)
    print(f"flake_campaign: {hunt.name}: syncing Python {hunt.python}", flush=True)
    sync = subprocess.run(sync_command(uv, hunt), cwd=options.root, env=env, check=False)
    if sync.returncode != 0:
        return Outcome(hunt, "didn't run", sync.returncode, None, "uv sync failed (see above)")
    print(f"flake_campaign: {hunt.name}: hunting", flush=True)
    process = subprocess.Popen(direct_command(options, hunt, out), cwd=options.root, env=env)
    try:
        code = wait(process)
    except Stopped:
        raise Stopped(outcome_of(hunt, process.returncode, out)) from None
    return outcome_of(hunt, code, out)


def build_image(docker: str, git: str, hunt: Hunt, root: Path) -> int:
    # Line endings come out as LF even under Git for Windows' core.autocrlf: .gitattributes sets
    # eol=lf, which git archive honours, so the Linux image gets the committed bytes.
    archive = subprocess.Popen([git, "archive", "HEAD"], cwd=root, stdout=subprocess.PIPE)
    try:
        built = subprocess.run(build_command(docker, hunt), cwd=root, stdin=archive.stdout)
    finally:
        if archive.stdout is not None:
            archive.stdout.close()
        archive.wait()
    return built.returncode or archive.returncode


def run_docker(options: Options, hunt: Hunt, docker: str, stamp: str, out: Path) -> Outcome:
    name = container(stamp, hunt)
    try:
        print(f"flake_campaign: {hunt.name}: hunting in {image(hunt)}", flush=True)
        process = subprocess.Popen(docker_command(docker, options, hunt, name), cwd=options.root)
        stopped = False
        try:
            code = wait(process)
        except Stopped:
            stopped, code = True, process.returncode
        subprocess.run(
            [docker, "cp", f"{name}:{CONTAINER_OUT}", str(out)],
            check=False,
            stdout=subprocess.DEVNULL,
        )
        result = outcome_of(hunt, code, out)
        if stopped:
            raise Stopped(result)
        return result
    finally:
        subprocess.run([docker, "rm", "--force", name], check=False, stdout=subprocess.DEVNULL)


# The report


def commit(git: str, root: Path) -> tuple[str, list[str]]:
    head = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
    ).stdout.strip()
    status = subprocess.run(
        [git, "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=False
    ).stdout.splitlines()
    return head or "unknown", status


def report_data(
    options: Options, outcomes: list[Outcome], head: str, changes: list[str], stopped: bool
) -> dict[str, Any]:
    return {
        "commit": head,
        "uncommittedChanges": changes,
        "machine": platform.platform(),
        "node": platform.node(),
        "workers": options.workers,
        "rounds": options.rounds,
        "loads": list(options.loads),
        "pythons": list(options.pythons),
        "direct": options.direct,
        "docker": options.docker,
        "selection": options.selection_label,
        "paths": list(options.selection),
        "stopped": stopped,
        "hunts": [each.record() for each in outcomes],
    }


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def report_markdown(data: dict[str, Any]) -> str:
    changes = " (with uncommitted changes)" if data["uncommittedChanges"] else ""
    stopped = " It was stopped part-way." if data["stopped"] else ""
    lines = [
        f"## Flake campaign on {data['machine']}, at `{data['commit'][:12]}`{changes}",
        "",
        f"{len(data['hunts'])} hunts of {data['workers']} workers x {data['rounds']} rounds over "
        f"{data['selection']}, loads {', '.join(map(str, data['loads']))}.{stopped}",
        "",
        "| Hunt | Python | Where | Load | Rounds | Failed | Result |",
        "|---|---|---|---|---|---|---|",
    ]
    for hunt in data["hunts"]:
        summary = hunt["summary"] or {}
        where = summary.get("platform", "n/a") if hunt["docker"] else "direct"
        if hunt["docker"]:
            where = f"Docker: {where}"
        result = hunt["status"] + (f": {hunt['reason']}" if hunt["reason"] else "")
        lines.append(
            f"| {hunt['hunt']} | {summary.get('python', hunt['python'])} | {_cell(where)} | "
            f"{hunt['load']} | {summary.get('roundsRun', 0)} | {summary.get('roundsFailed', 0)} | "
            f"{_cell(result)} |"
        )
    failing = [h for h in data["hunts"] if h["summary"] and h["summary"]["tests"]]
    crashed = [h for h in data["hunts"] if h["summary"] and h["summary"]["roundsWithoutReport"]]
    if failing or crashed:
        lines += ["", "### What failed"]
    for hunt in failing:
        for test in hunt["summary"]["tests"]:
            lines += [
                "",
                f"**{hunt['hunt']}**: `{test['test']}` failed in {test['failures']} of "
                f"{test['runs']} runs. First, in round {test['firstRound']}:",
                "",
                "<details><summary>" + _cell(test["message"])[:300] + "</summary>",
                "",
                "```",
                test["traceback"].rstrip(),
                "```",
                "",
                "</details>",
            ]
    for hunt in crashed:
        for each in hunt["summary"]["roundsWithoutReport"]:
            lines += [
                "",
                f"**{hunt['hunt']}**: round {each['round']} {each['status']} "
                f"(exit code {each['exitCode']}). It ended:",
                "",
                "```",
                "\n".join(
                    each["outputTail"].splitlines()[:60]
                    if each["outputTail"].startswith("Timeout (")
                    else each["outputTail"].splitlines()[-30:]
                ),
                "```",
            ]
    return "\n".join(lines) + "\n"


def write_report(out: Path, data: dict[str, Any]) -> None:
    (out / "campaign.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "report.md").write_text(report_markdown(data), encoding="utf-8")


# The campaign


def _tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise CampaignError(f"{name} isn't on the PATH, and the campaign needs it")
    return found


def preflight(options: Options) -> tuple[str, str, str | None]:
    """The tools the campaign needs, checked before any hunt runs."""
    uv, git = _tool("uv"), _tool("git")
    docker = None
    if options.docker:
        docker = _tool("docker")
        if subprocess.run([docker, "info"], capture_output=True, check=False).returncode != 0:
            raise CampaignError("docker is installed but its daemon isn't answering: start it")
        require_committed(commit(git, options.root)[1])
    return uv, git, docker


def require_committed(changes: list[str]) -> None:
    """Refuse a Docker campaign over uncommitted changes, naming them (design D11)."""
    if changes:
        listed = "\n  ".join(changes)
        raise CampaignError(
            "the working tree has uncommitted changes, and the Docker hunts would hunt the "
            f"commit, not the working tree:\n  {listed}\n"
            "Commit or stash them (git stash --include-untracked), then run the campaign again"
        )


def campaign(options: Options) -> tuple[list[Outcome], bool]:
    uv, git, docker = preflight(options)
    options.out.mkdir(parents=True, exist_ok=True)
    stamp = options.out.name.lower()
    head, changes = commit(git, options.root)
    outcomes: list[Outcome] = []
    stopped = False
    built: set[str] = set()
    previous_break = None
    if sys.platform == "win32":
        previous_break = signal.signal(signal.SIGBREAK, _raise_interrupt)
    plan = options.hunts()
    print(
        f"flake_campaign: {len(plan)} hunts of {options.workers} workers x {options.rounds} rounds "
        f"over {options.selection_label}, at {head[:12]}. Report: {options.out / 'report.md'}",
        flush=True,
    )
    try:
        for index, hunt in enumerate(plan, start=1):
            print(f"\nflake_campaign: hunt {index} of {len(plan)}: {hunt.name}", flush=True)
            out = options.out / hunt.name
            try:
                if hunt.docker and docker is not None:
                    if hunt.python not in built:
                        code = build_image(docker, git, hunt, options.root)
                        if code != 0:
                            outcomes.append(
                                Outcome(hunt, "didn't run", code, None, "the image didn't build")
                            )
                            continue
                        built.add(hunt.python)
                    outcomes.append(run_docker(options, hunt, docker, stamp, out))
                else:
                    outcomes.append(run_direct(options, hunt, uv, out))
            except Stopped as stop:
                if stop.args and isinstance(stop.args[0], Outcome):
                    result = stop.args[0]
                    result.status = "stopped"
                    outcomes.append(result)
                else:
                    outcomes.append(Outcome(hunt, "stopped"))
                stopped = True
                break
            finally:
                write_report(options.out, report_data(options, outcomes, head, changes, stopped))
    except KeyboardInterrupt:  # between hunts
        stopped = True
    finally:
        if previous_break is not None and sys.platform == "win32":
            signal.signal(signal.SIGBREAK, previous_break)
        write_report(options.out, report_data(options, outcomes, head, changes, stopped))
    return outcomes, stopped


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")
    options = parse_options(sys.argv[1:] if argv is None else argv)
    try:
        outcomes, stopped = campaign(options)
    except CampaignError as error:
        print(f"flake_campaign: {error}", file=sys.stderr)
        return 2
    print()
    for each in outcomes:
        print(f"flake_campaign: {each.hunt.name}: {each.status} {each.reason}".rstrip())
    print(f"flake_campaign: report in {options.out / 'report.md'}")
    if stopped:
        return 130
    return 0 if outcomes and all(each.status == "clean" for each in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
