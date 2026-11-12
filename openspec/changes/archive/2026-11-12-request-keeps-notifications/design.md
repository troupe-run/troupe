# Design: a request doesn't lose the notifications it reads past

## Context

Each runner plugin's tests drive the runner through a self-contained harness (`<runner>_harness.py`). Its reader
thread puts each line on a queue. `message()` takes the next one, and `request()` sends a request and takes messages
until its response, appending every message to `received` but returning only the response. `until_result()` takes
messages until a `run/event` of type `result`. See proposal.md for the failure and its reproduction.

Tests rely on `message()` and `rest()` reading only what comes *after* the last thing read. For example,
`test_cancel_during_a_held_response_closes_it_and_exits_without_a_result` (OpenAI) and the Ollama and Claude Code
cancel tests check that `rest()` after a cancel answer holds no `run/event`.

## Goals / Non-Goals

**Goals:**

- No harness reader waits for a message that `request()` has already taken off the stream.
- The OpenAI second-start test checks a second `run/start` while the first run is provably in flight, and fails at a
  named bound if the first run never ends.

**Non-Goals:**

- Changing any runner. The runners' handling of a second `run/start` is correct and covered.
- Sharing one harness across plugins. Plugins stay self-contained so they can be split out later.

## Decisions

### D1. Set the passed-over notifications aside for `until_result()` only

`request()` keeps each message it reads past in a set-aside list (they still go into `received` as now).
`until_result()` takes from that list first, in order, then from the stream. Taking a result clears what came before
it, so a later `until_result()` doesn't return it twice.

`message()` and `rest()` don't take from the list. They mean "what comes next on the stream", and the cancel tests use
`rest()` after an answer to check that nothing follows it. If they returned set-aside messages, those tests would see
events sent *before* the answer and fail, or (worse) be rewritten to allow them and stop checking what they check.

*Alternatives:* making `request()` return the passed-over messages alongside the response changes every caller (25
call sites across four plugins) for one reader's sake. Having the test look in `received` instead fixes this one test
and leaves the trap for the next test that calls `until_result()` after `request()`. Raising the 30 s bound fixes
nothing: the result never arrives on the stream again.

In the Claude Code tests `_until_result` is a function in the test module that calls `message()`, so the set-aside
list and the function that reads it move into `claude_harness.py`. The scripted harness has no `until_result()`, and
gets one, used by the test in D3.

### D2. A gate in the OpenAI fake endpoint

A new stream item, `Gate(event)`, makes the fake wait at that point in a reply until `event` is set or the fake stops,
flushing what came before it (as `Hold` does). The test streams `response.created`, the gate, then the rest of a text
reply:

1. `start`, then `fake.wait_for_requests(1, REQUEST_WITHIN)`: the run is now waiting on its reply.
2. `request("run/start", …)`: refused with `runner.already-started`.
3. Set the gate, then `until_result()`: the result is `ok`.

If the first run never ends, step 3 raises at the harness's `TIMEOUT` (30 s). The wait is wrapped so the failure
says it waited for the first run's result, not a bare `queue.Empty`.

The gate waits without a time bound of its own. That's safe because the fake stopping ends it, as it ends `Hold`, and
the `with FakeEndpoint(...)` block stops it however the test ends.

*Alternative:* `Pause(seconds)` would make the overlap likely, not certain: the same kind of margin that load uses up.

### D3. The scripted test is named for what it checks

The scripted runner plays a script with no step that waits for the test, and adding one changes its script language
and the scripted-runner spec, which is more than this fix needs. The test keeps its `wait` step, so on most runs the
second `run/start` lands mid-run, and reads with `until_result()`. It's renamed to say what it checks on every run:
the second `run/start` is refused, and the run still ends with its `ok` result and the events `init`, `result`.

## Risks / Trade-offs

- [The set-aside list hides a message from `message()`/`rest()` that a test expected to read next] → No current test
  reads a notification with `message()` after a `request()` that could have passed it. Apply runs every runner
  plugin's tests in full to show it, and the flake hunt in tasks repeats the fixed test under load.
- [A test's run ends before a `request()` and the result is set aside, so a test using `rest()` misses it] → Same as
  today: `rest()` never returned messages `request()` had taken. The set-aside list only adds a way to get them.
