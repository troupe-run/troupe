# troupe-runner-scripted

A deterministic actor runner for troupe's tests. It speaks the [runner contract](../../contributing/runners.md) over
standard input and output, imports nothing from troupe, and plays a script, or replays a recording, so that tests
can produce every run outcome on demand: offline, instantly and for free (decision
[#16](https://github.com/troupe-run/troupe/issues/16)).

```console
python -m troupe_runner_scripted
```

## Options

`run/start` options take exactly one of `script` (the script inline) or `scriptPath` (a JSON file), and optionally
`replayDelays` (`true` to replay a recording's timing). Any other option is refused, with an error naming it.

| Option | What it is |
|---|---|
| `script` | The script, inline (below) |
| `scriptPath` | The path of a JSON file holding the script |
| `replayDelays` | `true` to keep a recording's delays between records; default `false` |

## Schemas

The runner publishes its schemas in its package's [`schemas/`](src/troupe_runner_scripted/schemas/), installed with it, as every runner does
([Publishing a runner's schemas](../../contributing/runners.md#publishing-a-runners-schemas)):

- [`options.schema.json`](src/troupe_runner_scripted/schemas/options.schema.json): the options, every step and its fields, and a recording's
  lines (`$defs/recordingLine`). An event step is checked as the contract's run event, without `runId` and with
  `seq` optional. At run time the runner itself checks only that an event step has a `type`, so a test can still
  send a broken event on purpose with `rawStdout`.
- [`errors.schema.json`](src/troupe_runner_scripted/schemas/errors.schema.json): its own error codes, `scripted.invalid-script` and
  `scripted.unknown-option`, each with `details.where`, naming where in the options or script the problem is.

## Scripts

```json
{"onCancel": "honour", "steps": [
  {"event": {"type": "init", "runner": {"name": "scripted", "version": "0.1.0"}, "tools": ["Write"]}},
  {"transcript": "{\"type\":\"system\",\"subtype\":\"init\"}"},
  {"wait": {"ms": 50}},
  {"writeFile": {"path": "out/hello.txt", "content": "hi"}},
  {"event": {"type": "result", "status": "ok", "message": "done"}}
]}
```

Each step is an object with exactly one key, its kind. An unknown step, or an unknown field in one, is refused
before anything plays.

| Step | What it does |
|---|---|
| `event` | Sends a run event. `runId` and `seq` are filled in, unless the step sets them (to break the contract on purpose). |
| `transcript` | Sends a transcript record: a string, or `{"record": "...", "encoding": "base64"}`. |
| `stderr` | Writes text to standard error. |
| `wait` | `{"ms": n}`: waits, still answering troupe, so a cancel or end of input ends it early. |
| `writeFile` | `{"path": "...", "content": "..."}`: writes a file under the workspace. Absolute paths, drives, UNC paths and `..` are refused. |
| `hang` | `true`: blocks until a cancel it honours, `shutdown` or end of input. |
| `exit` | Exits at once with this code, without a `result`. |
| `rawStdout` | Writes this line to standard output as it is, to break the contract on purpose. |
| `replay` | Plays a recording (below). A relative path is found next to the script file, or in the workspace for an inline script. |
| `checkCharacter` | `{"hash": "sha256:..."}` (the SHA-256 of the character's UTF-8) or `{"absent": true}`: checks the character `run/start` carried. On a mismatch, sends an error `result` naming both and plays no later step, so a test can prove the character reached the runner. |

`onCancel` says what `run/cancel` does: `honour` (the default: answer and exit without a `result`, as Claude Code
does), `honour-with-result` (answer, send a `result` with status `error`, exit) or `ignore` (answer and carry on,
so only a kill stops it).

## Recordings

A recording is JSON Lines. Each line is `{"event": {...}}` or `{"transcript": "<native line>"}`, optionally with
`atMs`, the time it was sent. Replay sends each in order, unchanged except for the run id.

## Fixtures

[`fixtures/claude-code/`](fixtures/claude-code/) holds recordings captured from real Claude Code runs: the native
stream-json lines as they came, paired with the run events they map to, and each fixture's provenance. The Claude
Code runner's mapping is tested against them.

## Tests

The tests validate every message either side sends against the schemas in `protocol/` at the repository root, with
this runner's own schemas filling the contract's extension points. Options a test sends invalid on purpose must be
refused by the options schema too. If this plugin moves to its own repository, the contract's schemas come with it
as a copy.
