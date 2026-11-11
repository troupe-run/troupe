# Proposal

## Why

`troupe config set --json` refuses a value it can't read as JSON by quoting the whole value, so an endpoint holding
a password is printed back to standard error and carried in the client message (troupe-run/troupe#374):

```sh
troupe config set --json 'runtimes.box.endpoint=https://user:s3cretpw@example.com/v1'
# troupe: 'https://user:s3cretpw@example.com/v1' isn't JSON (Expecting value: line 1 column 1 (char 0)).
```

#323 (PR #373) made an endpoint refused for its user info repeated nowhere. This refusal is about JSON, not the
endpoint, so it falls outside that rule, but the effect is the same. An audit of every `config set`, `config unset`
and `config get` path finds the same echo in more places: every other value the CLI can't type (a boolean, a
number, a list or group, a path with no single type), a value file's YAML error (which quotes the file's line), a
malformed path in `config set` (whose error quotes the whole `path=value` argument), and core's schema refusals
(an enum's "not X", and jsonschema's own messages, which start with the value).

## What Changes

- A value the CLI can't type is refused naming the path and what the path takes, never the value. Under `--json`,
  the error says where the JSON stopped making sense (line and column) and why, in words that hold none of the value.
- A value read from a file (`path=@file`) that isn't JSON or YAML is refused naming the file and the line and
  column, never the parser's quoted excerpt of the file.
- A malformed config path names only the text read up to where reading failed, so the value after `=` in
  `config set` is never shown. This applies to `config set`, `config unset` and `config get` alike.
- Core's config check never repeats a value it refuses for its shape: an enum lists what's allowed without "not X",
  and a schema rule with no description is put in words that hold no value.
- Values that are names or theatre paths keep being named when the rule is about that name: an unknown runner, a
  runtime no config defines, and an `expect` path no effect covers. Each has already passed a check of its shape,
  and its fix is a command built from it.
- An effect pattern refused by the effects rules is refused for its shape, so it's no longer repeated: the error
  names the list, the pattern's position and the rule (owner, 2026-11-11).
- Tests with a canary password cover each `config set`, `config unset` and `config get` refusal, checking the CLI's
  standard error and the structured error the client receives.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `config`: "Command-line values are typed by the schema" refuses without repeating the value; "A malformed config
  path is refused" names the text only up to where reading failed; a new requirement says a refused config value
  is repeated nowhere, and which named values are exceptions.
- `effects`: "A pattern that can't be meant is refused" names the pattern's position instead of the pattern.

## Impact

- `packages/troupe/src/troupe/cli/values.py`: every refusal's problem and details.
- `packages/troupe/src/troupe/core/strict_json.py`: `StrictJSONError` carries a rule and position that hold no
  content; its message for troupe's own files is unchanged.
- `packages/troupe/src/troupe/core/config_paths.py`: `config.path-malformed`'s problem, fix and `details.text`.
- `packages/troupe/src/troupe/core/config/kinds.py`: `_rule` for `enum` and the jsonschema fallback, and the
  effect-pattern problem.
- `packages/troupe-plugin-sdk/src/troupe_plugin_sdk/effects.py`: `PatternError` gains a `rule` field; its message is
  unchanged.
- Tests: `test_cli_config.py`, `test_config_paths.py`, `test_config_kinds.py`, and a new canary test module.
- User docs that show these errors, if any quote a value (checked in tasks).
- No protocol, schema, event or runner change.
