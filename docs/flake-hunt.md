# Hunting flaky tests

`scripts/flake_hunt.py` repeats the tests on demand, to find the ones that fail only sometimes. Flaky tests used to
turn up one CI round at a time, mostly on Windows (#100). The hunt finds them in bulk, on your own machine, so each
can be fixed by its kind.

It runs the tests in **rounds**, each a separate pytest process, in several **workers** at once, so the rounds
overlap. It can also keep CPUs busy, because a timing flake rarely shows on an idle machine. Every round gets a
private, empty hypothesis database, so it explores new examples and never replays one saved by an earlier round or
commit. The repository's `.hypothesis/` is left alone.

It doesn't run in PR CI. Its own tests do, on all three platforms.

## Options

| Option | Meaning | Default |
|---|---|---|
| `--workers N` | Rounds run at once | 1 |
| `--rounds N` | Rounds each worker runs, back to back | 1 |
| `--load N` | CPUs to keep busy for the whole hunt (at most the CPUs it may use) | 0 |
| `--round-timeout SECONDS` | A round running longer is stopped and reported as hung | 1200 |
| `--out DIR` | Where the results go | a new directory under the system temp directory |
| `-k EXPRESSION` | Passed to pytest's `-k` | none |
| `PATH ...` | Test files, directories or ids | the whole suite |

A malformed option is refused before anything runs, naming the option, the value and what's allowed.

**The selection used on #100**, the tests that depend on time, processes, signals or file watching:

```
packages/troupe/tests/test_platform_append.py packages/troupe/tests/test_platform_environment.py
packages/troupe/tests/test_platform_files.py packages/troupe/tests/test_platform_interrupts.py
packages/troupe/tests/test_platform_locks.py packages/troupe/tests/test_platform_paths.py
packages/troupe/tests/test_platform_processes.py packages/troupe/tests/test_platform_watching.py
packages/troupe/tests/test_run_host.py packages/troupe/tests/test_cli_runs.py
packages/troupe-store-text/tests packages/troupe-vcs-git/tests plugins/runner-scripted/tests
```

It takes about 2 minutes a round on a laptop. The whole suite takes about 4.

## What it reports

Each round is printed as it ends:

```
w1r3 failed in 131.2s, 390 tests: packages/troupe/tests/test_run_host.py::test_a_quiet_runner_is_announced_as_silent
```

At the end, a summary names the platform, the interpreter, the workers, rounds and load, and the load average where
the platform has one. For every test that failed in any round, it gives the number of rounds that ran it, the number
that failed, and the first failure's message and traceback. A round that ended without a test report (pytest crashed,
collected nothing, or the round hung) is listed with the end of its output.

The hunt exits 0 when no round failed, 1 when one did, 2 for a refused option, and 130 when it was stopped.

The output directory holds the evidence:

| File | What |
|---|---|
| `summary.json` | The summary, as data |
| `results.jsonl` | One record per round, appended as each round ends, so a stopped hunt keeps what finished |
| `rounds/w<worker>r<round>.log` | The round's whole output, byte for byte |
| `rounds/w<worker>r<round>.xml` | pytest's JUnit report for the round |
| `hypothesis/w<worker>r<round>/` | The round's hypothesis database, holding any failing example it found |
| `load.json` | The load processes' pids |

**Stopping:** Ctrl-C (or Ctrl-Break on Windows) stops the running rounds and the load, then prints the summary of the
rounds that finished. Stopping a round stops everything it started, including a process whose parent has already
exited. On Windows that holds even if the hunt itself is killed.

## macOS and Linux

```console
uv run scripts/flake_hunt.py --workers 3 --rounds 10 <selection>
uv run scripts/flake_hunt.py --workers 3 --rounds 10 --load 2 <selection>
```

To hunt on Python 3.13 without touching the 3.12 environment you develop in, give 3.13 an environment of its own.
`uv run --python 3.13` alone would re-sync `.venv` to 3.13.

```console
UV_PROJECT_ENVIRONMENT=.venv-3.13 uv run --python 3.13 scripts/flake_hunt.py --workers 3 --rounds 10 <selection>
```

`.venv-*/` is ignored by git, so ruff skips it too.

## Linux in Docker

The image is built from the committed tree (`git archive HEAD`), so commit what you want to hunt first. The container
works on its own copy: a bind mount from the host would change how file locking and watching behave.

```console
git archive HEAD | docker build -t troupe-hunt:3.12 --build-arg PY=3.12 -f scripts/flake_hunt.Dockerfile -
docker run --init --name hunt troupe-hunt:3.12 --workers 3 --rounds 10 <selection>
docker cp hunt:/home/hunter/out ./flake-hunt-out
docker rm hunt
```

For 3.13, build with `--build-arg PY=3.13` and tag it `troupe-hunt:3.13`. Options after the image name go to the hunt,
and its results go to `/home/hunter/out` in the container.

- **`--init` is needed.** Without an init process as PID 1, killed processes' orphans are never reaped. They stay
  zombies, which read as running, and the kill-the-whole-tree tests fail for a reason no CI runner has (#100).
- **The image runs as an ordinary user**, as CI does, because root changes what `chmod` and `kill(pid, 0)` do.
- **One test fails in every container round:** `test_pid_1_which_the_os_refuses_to_let_us_signal_reads_as_running`.
  In a container, PID 1 belongs to the hunt's own user, so the refusal the test depends on doesn't happen. That's
  the container, not a flake.

## Windows

You need [uv](https://docs.astral.sh/uv/) and [Git for Windows](https://gitforwindows.org/) on the `PATH`. Run the hunt
from PowerShell, at the repository root:

```powershell
uv run scripts/flake_hunt.py --workers 3 --rounds 10 <selection>
uv run scripts/flake_hunt.py --workers 3 --rounds 10 --load 2 <selection>
```

For Python 3.13, in an environment of its own:

```powershell
$env:UV_PROJECT_ENVIRONMENT = ".venv-3.13"
uv run --python 3.13 scripts/flake_hunt.py --workers 3 --rounds 10 <selection>
Remove-Item Env:UV_PROJECT_ENVIRONMENT
```

- **Use Windows Terminal**, or don't click in the console window during a hunt. A classic console window has
  QuickEdit mode: a click starts a selection, which pauses everything that writes to the window, the hunt included,
  until you press a key.
- **Note whether Microsoft Defender real-time protection is on.** It slows file operations, so it's part of the
  evidence. Don't turn it off just for the hunt: troupe's users have it on.
- Ctrl-C or Ctrl-Break stops the hunt.
- A traceback the console's code page can't show still prints, with those characters escaped. The JSON files hold
  them unchanged.

## Putting a finding on #100

For each test that failed, add a line to #100's "Found so far" list with:

- the test id, and the platform, Python version, workers, rounds and load from the summary;
- how often it failed (`2 of 30 runs`), and the first failure's message;
- the traceback, or the end of the round's output for a crash or a hang;
- its kind, from #100's table, if you can tell. If it fits no kind, say so.

The output directory has everything else. Attach `summary.json` if the traceback is long.
