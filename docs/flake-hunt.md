# Hunting flaky tests

`scripts/flake_hunt.py` repeats the tests on demand, to find the ones that fail only sometimes. Flaky tests used to
turn up one CI round at a time, mostly on Windows (#100). The hunt finds them in bulk, on your own machine, so each
can be fixed by its kind.

It runs the tests in **rounds**, each a separate pytest process, in several **workers** at once, so the rounds
overlap. It can also keep CPUs busy, because a timing flake rarely shows on an idle machine. Every round gets a
private, empty hypothesis database, so it explores new examples and never replays one saved by an earlier round or
commit. The repository's `.hypothesis/` is left alone.

It doesn't run in PR CI. Its own tests do, on all three platforms.

## The campaign: the agreed hunt, in one command

`scripts/flake_campaign.py` runs the hunt #100 agreed as "done", one hunt after another: `--workers auto` × 10
rounds, without load and with `--load 2`, on every supported Python version (`scripts/python_versions.py`, whose
check keeps them equal to CI's matrix).
With `--docker` it then runs the same hunts in the Linux container. It hunts the OS-sensitive tests below unless you
pass `--all` (the whole suite) or test paths.

```console
uv run scripts/flake_campaign.py              # direct only
uv run scripts/flake_campaign.py --docker     # direct, then in Docker
```

The same commands work in PowerShell on Windows, where `--docker` uses Docker Desktop's Linux containers.

- **Each Python version gets its own environment**, `.venvs/<version>`, the one `scripts/on.py` uses, synced before
  its hunts. `.venv` is never touched, whatever Python it holds.
- **Workers:** `auto` by default: three quarters of the CPUs the hunt may use, less the load. On 8 logical CPUs that's
  6 workers without load, and 4 workers plus 2 busy CPUs with load, so the load adds to the same share of the
  machine instead of oversubscribing it. In Docker, each hunt counts the container's own CPUs. The report shows the
  number each hunt used.
- **With `--docker`, commit first.** The image is built from the commit, so the campaign refuses to start over
  uncommitted changes, and lists them. Otherwise the direct and Docker hunts would hunt different code.
- **How long:** each hunt takes about 10 rounds of the selection. That's roughly 25 minutes on a laptop for the
  OS-sensitive tests. With four supported Pythons (3.12 to 3.15) and two loads, that's 8 hunts: about 3.5 hours
  direct, and about 7 with `--docker`. Leave it running. Ctrl-C (or Ctrl-Break) stops the running hunt cleanly, runs
  no more, and still writes the report.
- **The report** is written after every hunt, to `report.md` (Markdown, ready to paste on #100) and `campaign.json`,
  in the directory printed at the start, by default `flake-campaign/<timestamp>` under the system temp directory.
  It names the commit, the machine, each hunt with its result, and every failing test with its runs, failures and
  first traceback. Each hunt's own results are in a subdirectory named after it, such as `direct-3.12-load2`.
- The campaign exits 0 only when every hunt was clean, 1 when one failed or didn't run, 2 when it refused to start,
  and 130 when it was stopped.

Options: `--workers`, `--rounds`, `--loads 0,2` and `--pythons 3.12,3.13` change the plan. Change it only to try
something out. The agreed campaign is the default.

## Options

| Option | Meaning | Default |
|---|---|---|
| `--workers N` | Rounds run at once: a number, or `auto` for three quarters of the CPUs the hunt may use, less the load | 1 |
| `--rounds N` | Rounds each worker runs, back to back | 1 |
| `--load N` | CPUs to keep busy for the whole hunt (at most the CPUs it may use) | 0 |
| `--round-timeout SECONDS` | A round running longer is stopped and reported as hung | 1200 |
| `--stall SECONDS` | A single test running longer has every thread's stack written to the round's output, so a hung round names its test | 300 |
| `--out DIR` | Where the results go | a new directory under the system temp directory |
| `-k EXPRESSION` | Passed to pytest's `-k` | none |
| `PATH ...` | Test files, directories or ids | the whole suite |

A malformed option is refused before anything runs, naming the option, the value and what's allowed.

**The selection used on #100**, the tests that depend on time, processes, signals or file watching. The campaign
hunts these by default: its `SELECTION` names them as patterns, so a new `test_platform_*.py` file joins on its own.

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
uv run scripts/flake_hunt.py --workers auto --rounds 10 <selection>
uv run scripts/flake_hunt.py --workers auto --rounds 10 --load 2 <selection>
```

`--workers auto` picks three quarters of the CPUs the hunt may use, less the load.

To hunt on another supported Python without touching the environment you develop in, run it through `scripts/on.py`,
which gives each version its own environment in `.venvs/<version>`:

```console
uv run scripts/on.py 3.13 scripts/flake_hunt.py --workers auto --rounds 10 <selection>
```

## Linux in Docker

The image is built from the committed tree (`git archive HEAD`), so commit what you want to hunt first. The container
works on its own copy: a bind mount from the host would change how file locking and watching behave.

```console
git archive HEAD | docker build -t troupe-hunt:3.12 --build-arg PY=3.12 -f scripts/flake_hunt.Dockerfile -
docker run --init --name hunt troupe-hunt:3.12 --workers auto --rounds 10 <selection>
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
uv run scripts/flake_hunt.py --workers auto --rounds 10 <selection>
uv run scripts/flake_hunt.py --workers auto --rounds 10 --load 2 <selection>
```

For Python 3.13, in its own environment:

```powershell
uv run scripts/on.py 3.13 scripts/flake_hunt.py --workers auto --rounds 10 <selection>
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

After a campaign, post its `report.md` on #100 as it is. Then add a line for each new failure, as below.

For each test that failed, add a line to #100's "Found so far" list with:

- the test id, and the platform, Python version, workers, rounds and load from the summary;
- how often it failed (`2 of 30 runs`), and the first failure's message;
- the traceback, or the end of the round's output for a crash or a hang;
- its kind, from #100's table, if you can tell. If it fits no kind, say so.

The output directory has everything else. Attach `summary.json` if the traceback is long.
