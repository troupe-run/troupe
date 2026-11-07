# troupe-runner-scripted

A deterministic actor runner for troupe's tests. It speaks the [runner contract](../../contributing/runners.md) over
standard input and output, builds on the [plugin SDK](../../packages/troupe-plugin-sdk/README.md) and imports nothing
else from troupe, and plays a script, or replays a recording, so that tests
can produce every run outcome on demand: offline, instantly and for free (decision
[#16](https://github.com/troupe-run/troupe/issues/16)).

```console
python -m troupe_runner_scripted
```

## Options

The runner takes a runtime optionally (troupe's runner table says `optional`): `run/start` may carry one, and
only the `checkRuntime` and `echoCredential` steps use it.

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
| `event` | Sends a run event. `runId` and `seq` are filled in, unless the step sets them (to break the contract on purpose), and so is an `init`'s `effects`, as `checked`. |
| `transcript` | Sends a transcript record: a string, or `{"record": "...", "encoding": "base64"}`. |
| `stderr` | Writes text to standard error. |
| `wait` | `{"ms": n}`: waits, still answering troupe, so a cancel or end of input ends it early. |
| `writeFile` | `{"path": "...", "content": "..."}`: writes a file under the workspace, raw: no effect checks it, so a test can show what troupe's audit catches. Absolute paths, drives, UNC paths and `..` are refused. |
| `tool` | `{"name": "Write", "input": {...}, "callId": "c1", "isError": true}`: carries out one tool call with the [plugin SDK's tools](../../packages/troupe-plugin-sdk/README.md), as a model's call would be: checked against `run/start`'s effects, in its workspace and scratch directory, and sent as a `tool_call` and a `tool_result`. `input` is an object of the tool's fields, or the JSON text of one (malformed on purpose, if need be). `callId` is `tool-<n>` when absent. With `isError`, a result that isn't what the step expects ends the run with an error `result` naming the step. |
| `hang` | `true`: blocks until a cancel it honours, `shutdown` or end of input. |
| `exit` | Exits at once with this code, without a `result`. |
| `rawStdout` | Writes this line to standard output as it is, to break the contract on purpose. |
| `replay` | Plays a recording (below). A relative path is found next to the script file, or in the workspace for an inline script. |
| `checkCharacter` | `{"hash": "sha256:..."}` (the SHA-256 of the character's UTF-8) or `{"absent": true}`: checks the character `run/start` carried. On a mismatch, sends an error `result` naming both and plays no later step, so a test can prove the character reached the runner. |
| `checkRuntime` | `{"name": "...", "endpoint": "...", "model": "...", "credentialHash": "sha256:...", "price": {...}}` (any of them, `"noCredential": true` in place of a hash for none, `"noPrice": true` in place of a price for none) or `{"absent": true}`: checks the runtime `run/start` carried, its price rate for rate, and the credential in `TROUPE_RUNTIME_CREDENTIAL` by its hash. On a mismatch, sends an error `result` naming each field that differs, a credential only by its hash, and plays no later step. |
| `echoCredential` | `true`. **Only for testing troupe's masking:** sends the run's credential back in a `log` event, a transcript record and standard error, as a runner that leaks it would. A real runner never does. With no credential, ends the run with an error `result`. |

`onCancel` says what `run/cancel` does: `honour` (the default: answer and exit without a `result`, as Claude Code
does), `honour-with-result` (answer, send a `result` with status `error`, exit) or `ignore` (answer and carry on,
so only a kill stops it).

## Recordings

A recording is JSON Lines. Each line is `{"event": {...}}` or `{"transcript": "<native line>"}`, optionally with
`atMs`, the time it was sent. Replay sends each in order, unchanged except for the run id.

## Fixtures

The Claude Code runner keeps recordings captured from real Claude Code runs, in
[`plugins/runner-claude-code/fixtures/claude-code/`](../runner-claude-code/fixtures/claude-code/): the native
stream-json lines as they came, paired with the run events they map to, and each fixture's provenance. The Claude
Code runner's mapping is tested against them, and this runner replays them through troupe's host.

## Tests

The tests validate every message either side sends against the schemas in `protocol/` at the repository root, with
this runner's own schemas filling the contract's extension points. Options a test sends invalid on purpose must be
refused by the options schema too. If this plugin moves to its own repository, the contract's schemas come with it
as a copy.
