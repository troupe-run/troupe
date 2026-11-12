# Tasks

## 1. The output-limit case can't race the first wait (D1, #395)

- [ ] 1.1 Force the old race: an uncommitted stand-in for `processes.time.monotonic` sleeps 0.5 s on the call that
  starts the loop's clock. Verify: on the current test, `[passes its output limit]` fails with "no bounded wait was
  made". Record the output for the PR.
- [ ] 1.2 Give `_record_the_waits` an `on_first_wait` that the recording `Event.wait` and `Popen.wait` call once,
  bounded or not, and make `_OVERFLOWS` a template that waits for a gate file (5 ms polls, gives up after 20 s
  without writing). The test opens the gate under `tmp_path` when the first wait starts. Verify: all four cases pass,
  and with 1.1's stand-in the output-limit case passes too.
- [ ] 1.3 Put a fixed tick back, first as `time.sleep(0.02)` and then as `output.changed.wait(0.02)` in
  `run_to_completion` (uncommitted). Verify: the output-limit case fails with both, on the sleep and on the 20 ms
  asked for.

## 2. The latency test times from the command's end (D2, #398)

- [ ] 2.1 Replace `test_a_command_that_exits_at_once_costs_about_what_starting_it_directly_costs` with
  `test_a_command_returns_as_soon_after_it_ends_as_one_started_directly`: 30 interleaved runs each way of a Python
  child that sleeps `0.020 * i / 30` s, stamps `time.perf_counter()` and calls `os._exit(0)`. Check every direct
  latency is at least 0, then that the median difference is under 5 ms. Verify: it passes 10 times in a row alone.
- [ ] 2.2 Put the 20 ms tick back both ways as in 1.3. Verify: the new test fails each time it's run (5 runs per
  patch), with the medians in its message.

## 3. Checks

- [ ] 3.1 Flake hunt, one test at a time: check `uptime` (1-minute load under 40), then run
  `uv run scripts/flake_hunt.py --load 2` on the output-limit case, and after that on the latency test. Verify: no
  failures. `pgrep -fl "fake_claude.py|while True: pass"` shows nothing of this session's afterwards. Record rounds
  and load in the PR.
- [ ] 3.2 `uv run scripts/check.py` passes.

## Workflow follow-up

- Draft PR closing #395 and #398, act on Claude's review, mark ready, CI green on all three platforms.
- `/opsx:archive` on the branch before the merge.
