# Proposal

## Why

Flaky tests keep turning up one at a time, each on whichever pull request happens to hit it (#81, #90, #91, #96, #97),
and each costs a CI round to find and a whole issue, change and pull request to fix (#100). A first sweep on #100
showed why waiting for CI is a poor way to find them: about 150 CI runs gave 11 intermittent failures, 9 on Windows,
and 30 rounds of the OS-sensitive tests under moderate load passed cleanly on both macOS and Linux. Finding them
needs repeated runs on demand, on every platform, the Windows PC included. The same sweep found a race that only an
injected delay showed: the scripted runner can read the host's `shutdown` before it plays the steps after its
result, so a script can't reliably produce "an ok result, then an unclean exit".

## What Changes

- **A hunt script, `scripts/flake_hunt.py`,** run with `uv run`, that:
  - runs the tests (all of them, or a selection by path and `-k`) for a set number of rounds, in several workers at
    once, so the runs overlap;
  - optionally keeps a set number of CPUs busy, so timing flakes show up on an idle machine;
  - gives every round a fresh, private hypothesis database, so each round explores new examples, never replays an
    old one, and never writes into the repository's `.hypothesis/` (a saved failure there fails every later local
    commit);
  - prints each round as it ends, then a summary per failing test: runs, failures, and the first failure's message
    and traceback, with the platform, Python version and load;
  - writes the same results as JSON, so a finding can go on an issue as evidence;
  - refuses malformed options with an error that names the option and the fix;
  - stops its workers and load cleanly on Ctrl-C (and Ctrl-Break on Windows), and leaves nothing running, a hung
    round included;
  - treats Windows as the main target, since that's where most flakes are: each round's process tree is held in a
    job from before it runs (so the venv launcher's interpreter and orphaned grandchildren can't escape), a
    traceback the console can't encode still prints, and each Python version gets its own environment.
- **How to run it,** in `docs/`: on macOS, on Linux in Docker, and on Windows. The Docker image runs as an ordinary
  user with `--init`, because without an init that reaps orphans, killed runners' children stay zombies and the
  kill-the-tree tests fail for a reason CI never has (#100).
- **The scripted runner plays a script's instant steps without stopping to read messages,** and answers what troupe
  sent when it reaches a step that waits, a hang, or the end of the script. A script can then produce an ok result
  followed by an unclean exit, or a late event, on every run, whatever the timing. The two `test_run_host` tests that
  depend on it stop being exposed to the race.
- Each flake the hunt finds later becomes a task appended to this change and a line on #100, as #100 sets out.

## Capabilities

### New Capabilities

- `flake-hunt`: hunting flaky tests on demand. Repeated, overlapping rounds with optional load and fresh randomised
  inputs, a per-test summary with the evidence, and how to run it on each platform.

### Modified Capabilities

- `scripted-runner`: "A script is a list of steps played in order" says when the runner reads troupe's messages while
  it plays a script: at a step that waits, at a hang, and at the end, not between instant steps.
- `platform`: the lock and file-replacement waits are announced before they time out, even when a stall carries them
  past both (found by the hunt on Windows, #100). Later flake fixes in `troupe.platform` (watching a directory
  removed while it is watched, a watch wait returning before its timeout) add their scenarios here too.
- `platform` and `event-store`: the watched-delivery scenarios state their timing as the fastest of five deliveries
  under 0.25 s, with the median within 0.25 s plus an allowance for a loaded machine, in place of a median under
  0.25 s (#100, #89; the rule #91 set for polled deliveries).

## Impact

- New: `scripts/flake_hunt.py`, its tests in `scripts/tests/`, a Dockerfile for the Linux hunt, and a page in `docs/`.
- `plugins/runner-scripted/src/troupe_runner_scripted/runner.py`: when the script loop reads messages.
- `plugins/runner-scripted/tests/`, `packages/troupe/tests/test_run_host.py`: tests that pin the new ordering.
- `openspec/specs/scripted-runner/spec.md`, through this change's delta, and a new `openspec/specs/flake-hunt/`.
- No dependency changes: the script uses the standard library and the pytest already in the workspace. It doesn't run
  in PR CI, and needs no self-hosted runner.
- Out of scope here: the other suspects #100 lists from reading (announce and timeout bounds too close together,
  sleeps as synchronisation, the Windows deadline loop, the signal handler's locks, the Windows job assignment, the
  git variable gap). Each becomes a task when the hunt shows it fails, or gets its own issue when it isn't a flake.
