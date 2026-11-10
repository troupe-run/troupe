# Design

## Context

See proposal.md for why. The current state:

- `run_to_completion` (`packages/troupe/src/troupe/platform/processes.py`) starts the command with `subprocess.Popen`,
  drains stdout and stderr on two threads (`_Output.drain`), and loops: is the process done and are both drain
  threads dead, has output overflowed, has the timeout passed, is it time to announce, then `time.sleep(0.02)`. The
  first check almost always finds the command still running, so every call costs at least 20 ms.
- `GitAdapter._current()` (`packages/troupe-vcs-git/src/troupe_vcs_git/__init__.py`) keeps one snapshot behind the
  branch token (cache-vcs-state design D1). When the stats differ, the last read was racy (D4), or there's no
  snapshot yet, it runs `symbolic-ref --quiet HEAD`, then `symbolic-ref --quiet --short HEAD` (D2), then
  `rev-parse --verify --quiet HEAD`. Adapters are made per use through `load_vcs` (`core/events/service.py`,
  `troupe_store_text`), so each new adapter starts with no snapshot.
- The spike's event wait is in the spike session's scratchpad (`eventwait.py`, installed by an import-time patch). It
  isn't on any branch, so it's described here and rewritten, not cherry-picked.

## Goals / Non-Goals

**Goals:**

- No fixed tick in `run_to_completion`. Its timeout, overflow, announcement and held-output behaviour stays as the
  `platform` spec says, on all three platforms.
- Count why branch and HEAD reads miss the cache before changing anything that depends on the reason, and record the
  counts.
- The fewest git processes per re-read that give exactly git's answers.

**Non-Goals:**

- `ChildProcess.wait`'s 20 ms: it's an `asyncio.wait` timeout that returns as soon as the child exits.
- `core/runners/host.py`'s watchdog tick and `SUBSCRIBE_POLL_SECONDS`: the spike measured no gain from either.
- Other git calls (`ls-files -u`, `rev-parse --git-path MERGE_HEAD`, `HEAD^@`, test fixtures' `git init`): not in #361.
  If the counts show a cheap win there, it becomes a new issue.
- Changing what lineage records for the branch (D2 of cache-vcs-state stays).

## Decisions

### D1: `run_to_completion` waits on one event, set by the drain threads

The two drain threads each set a per-stream "ended" flag and then a shared `threading.Event` (`changed`) when their
pipe closes, in a `finally`. The overflow check sets `changed` too. The loop:

1. `changed.clear()`.
2. If output has overflowed: kill the tree, raise OutputTooLargeError.
3. The next deadline is the announce time until the announcement has fired, then the timeout.
4. If both streams' ended flags are set: `process.wait(timeout=<time to the next deadline>)`, and return on success.
5. Past the timeout: kill the tree, raise ProcessTimeoutError with the output so far. Past the announce time: announce
   once.
6. `changed.wait(<time to the next deadline>)`, then go round again.

**The ended flags, not `Thread.is_alive()`.** The spike checked `is_alive()` after clearing the event. A drain
thread sets the event in its `finally` and is still alive for a moment afterwards. If the loop clears and checks in
that moment, it sees a live thread, and its next wait has already lost the set, so it sleeps to the announce time
(1 s for git) and announces a wait that never happened. A flag set before the event, and read after the clear,
closes that gap: either the read sees the flag, or the event is set after the clear and the wait returns at once.
A test holds a drain thread between setting the event and returning to prove it.

**`process.wait` with a timeout after the pipes close.** Both pipes closed means the command exited or closed its
output, so the wait is short. On Windows it's `WaitForSingleObject`. On POSIX, CPython polls `waitpid(WNOHANG)` with
a backoff starting at 0.5 ms, so a command that has already exited returns at the first check. A command that closes
its output and keeps running is bounded by the next deadline, as before.

**What doesn't change:** a command that exits while a grandchild holds its output open still counts as running,
because its pipes haven't closed. The kill path, the Windows job object and `_feed` (stdin) are untouched, and the
loop still never waits on the stdin thread.

*Alternatives:* a 1 ms poll (the spike measured 452 / 451 s, against a baseline that wasn't interleaved). It also
wakes each running command a thousand times a second, so it isn't taken. Selectors on the pipes don't work for pipes
on Windows. asyncio would need an event loop, and `run_to_completion` has to work inside a running one.

### D2: How the latency is pinned in tests

- **Deterministic:** wrap `processes.time.sleep` so it fails the test if called, and record every timeout passed to
  the event's `wait` and to `process.wait`. Run a command that ends at once, one that times out and one that is
  announced. Each recorded wait is the time left to the next deadline, never a short fixed tick. This is the primary
  pin. It fails on today's loop (it calls `time.sleep(0.02)`), and runs the same on every OS.
- **Measured:** run `git --version` 20 times through `run_to_completion`, interleaved with 20 runs through
  `subprocess.run`. The median difference must be under 10 ms, half the old tick. Today's loop costs at least 20 ms
  whatever the command takes, so it fails. The medians and the interleaving keep load on a CI runner from flaking it.
- Overflow at once: a command writes past the limit and then sleeps for 60 s. The OutputTooLargeError arrives well
  before the announce time (set to 30 s), and no announcement is made.
- The existing tests stay as they are: timeout with a grandchild, the early grandchild on Windows, overflow, inside an
  event loop, the single announcement, and the held output still timing out.

### D3: Counting why reads miss the cache, before the cache changes

`_current()` gets a temporary, uncommitted wrapper, installed the way the spike installed its patches (an opt-in
`.pth` in `.venv`, active only while a flag file exists). It logs one line per call to the read path. Each line has
the test or process, the adapter's id, and the reason:

| Reason | Meaning |
|---|---|
| `new` | the adapter has no snapshot yet |
| `racy` | the snapshot was racy (D4) and the stats still match |
| `watched:<file>` | the first watched file whose stat differs: `HEAD`, `index`, `logs/HEAD`, `packed-refs`, `tables.list` |
| `ref` | only the branch's ref file differs |

Each line also says whether the re-read found a different branch or HEAD (`moved`) or the same (`same`). `same`
re-reads are the ones a cache change could save, and the reason column says which change. It runs over:

- the full suite, 3 xdist workers, with the log aggregated across workers;
- a real `troupe perform` with the scripted runner in a fresh theatre, as in `docs/opening-night/first-performance.md`.

The tables go into this design (D5 below, filled in at apply) and on #361. Nothing from the wrapper is committed.

*Alternative:* a committed per-adapter `Counter` of reasons, like `commands_run`. It would let tests assert reasons,
but it's product code kept only for measuring. The tests below assert command counts instead, which is what the
spec promises.

### D4: One `rev-parse` for a HEAD that has a commit

A re-read runs:

```
git rev-parse HEAD --symbolic-full-name HEAD --abbrev-ref=loose HEAD --
```

It prints HEAD's commit, the full ref name (`HEAD` when detached) and the short name (`HEAD` when detached), then `--`.
Probed on git 2.56 (2026-11-11):

- **`=loose` is required.** Plain `--abbrev-ref` is strict, and gives `heads/main` when `refs/remotes/main` or
  `refs/remotes/main/HEAD` exists. `symbolic-ref --short` gives `main` there, and so does `--abbrev-ref=loose`. With a
  tag `main`, a `refs/main`, and branches named `heads/x` and `tags/main`, all three forms agree.
- Detached HEAD: `HEAD` and `HEAD` for the names, so no branch and no ref path. Today the ref path is `None` when
  detached, which this keeps.
- A file named `HEAD` in the work tree: same answers, with or without `--`. The `--` stays so git never reads a
  name as a path.
- Unborn HEAD (no commit yet, or an orphan branch): `rev-parse` exits 128 with "bad revision". Then the adapter runs
  today's three commands unchanged. That path tells an unborn HEAD from a real failure without parsing git's message,
  because `symbolic-ref` and `rev-parse --verify --quiet` already do (exit 1 means no answer, anything else is
  vcs.failed). An unborn re-read costs four commands instead of three. D5's counts say how often that happens.

The order "stat, then read" (cache-vcs-state D1) is kept: stats are taken before the command, and the ref's stat
after the command has named it.

*Alternatives:* `for-each-ref --include-root-refs` with `%(symref)`, `%(symref:short)` and `%(objectname)` gives all
three in one process for a born HEAD, but needs git 2.46 and also skips an unborn HEAD. Stripping `refs/heads/` in
Python would change the recorded branch for ambiguous names (cache-vcs-state D2). `git branch --show-current` has no
disambiguation.

**Proof:** a differential property test. Hypothesis generates sequences of operations (commits, switches, detaches,
orphan branches, tags and remote refs named after the branch, branches named `heads/…` and `tags/…`, a file named
`HEAD`), with both ref storages. After each one, it compares the adapter's answers with git's own
`symbolic-ref --quiet --short HEAD` and `rev-parse --verify --quiet HEAD`. It's written first and passes on today's
three-command read before the change (learned rule: test a rewrite of input handling against the old behaviour).

### D5: Cuts the counts may justify (decided at apply, with the owner where the rule is touched)

D4 cuts every born-HEAD miss from three processes to one, whatever the reason, so it doesn't wait on the counts.
Anything beyond it depends on the counts, and it's decided against them:

- **Many `new` misses within one command:** share one adapter per theatre within a command, so the event service and
  the text store don't each start cold. This keeps #75's rule entirely.
- **Many unborn re-reads:** order the unborn path so it costs no more than today's three.
- **Many `racy` or `watched:index` re-reads that find `same`:** these are what #75's rule (D4's racy rule, D3's
  watched files) requires. Narrowing the racy window on file systems with fine timestamps, or not re-reading for an
  index-only change, changes the rule. Either is raised with the owner, with the counts, before any code depends on
  it. The default is to keep the rule.

The counts, the choice and its reason are written here before the code that depends on them.

### D6: How the suite is measured

On macOS, against a baseline at this change's base commit in a separate detached worktree:

- `uv run pytest -n 3 --basetemp=<fresh dir> -p no:cacheprovider`, alternating baseline and change, at least two
  runs each, only while `uptime`'s load average is under 20. Wall time, and worker time from `--durations=0`.
- The per-call cost: `git rev-parse HEAD` 200 times through `subprocess.run`, through today's `run_to_completion` and
  through the new one.
- Git processes across the suite, by command, with the spike's spawn counter (`spawncount.py`), before and after.
- CI: the pytest time on each of the three legs from the job logs, against the last `main` run.

The numbers go in a "Measured" section here and on the pull request.

## Risks / Trade-offs

- [The Windows kill path and the event wait haven't run together] → The Windows leg runs the whole
  test_platform_processes file, including the early-grandchild job test. The PR isn't marked ready until all three
  legs pass.
- [The measured latency test flakes on a loaded runner] → Medians of 20 interleaved runs, with a threshold at half
  the old tick. The deterministic test is the real pin. If the measured one flakes, it gets fixed or removed in this
  change, not retried.
- [`--abbrev-ref=loose` disagrees with `symbolic-ref --short` in a case not probed] → The differential property test
  over ambiguous names, both ref storages, and a run of the existing state-cache tests (`TestMoves…`).
- [The timing runs overload the machine other sessions share] → Owner told before the runs start. Runs only below
  load 20, in sequence.
- [The counts show the rule itself is the cost] → It stays as it is unless the owner decides otherwise (D5).

## Migration Plan

None. No settings, events or stored formats change. Rolling back is reverting the commits.
