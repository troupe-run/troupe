# Design

## Context

See proposal.md, "Why", for the problem. Where values are read and refused today:

| Where | What it repeats now |
|---|---|
| `cli/values.py`, `--json` | `{text!r} isn't JSON ({error})`: the whole value |
| `cli/values.py`, boolean / number | `is true or false, not {text!r}`, `is a number, not {text!r}` |
| `cli/values.py`, list or group | `{text!r} isn't JSON (...)` |
| `cli/values.py`, no single type | `can't tell how to read {text!r}` |
| `cli/values.py`, `@file` | `{file} isn't JSON or YAML: {error}`: ruamel's message quotes the broken line of the file |
| `core/strict_json.py` | a repeated key is named (`the key 'x' appears more than once`): a key inside the value |
| `core/config_paths.py` | `"{text}" isn't a config path` and `details.text`: for `config set`, `text` is the whole `path=value` argument; the dot-before-bracket fix rewrites the whole text |
| `core/config/kinds.py`, `_rule` | `enum`: `not {instance!r}`; any rule with no description: jsonschema's own message, which starts with the value (`'x' is too short`, `5 is less than the minimum of 6`) |
| `core/config/kinds.py`, effect patterns | the SDK's `PatternError` message, which quotes the pattern, and a fix that quotes it again |
| `core/config/kinds.py`, names | an unknown runner, a runtime config doesn't define, an `expect` path no effect covers |
| `core/config/kinds.py`, `_move_fix` | the actor's own options and model, in the `troupe config set` that moves them; an endpoint with `@` is already `<url>` (#323) |

Paths not affected: `config get` prints what config holds, which is what it's for; its conflicts show the conflicting
values, which config holds too. `config get --resolved` refuses a runtime variable without its value already
(`runtime.invalid-value`, #298), and an endpoint variable with a password is covered by #323's test. `config unset`
takes only paths. A file path that can't be read (`@file`) names the path the person typed, not a value.

The CLI types a value before any request is sent, so its refusals are `TroupeError`s raised in the CLI; core's are
raised behind the dispatcher and reach the CLI as the client message. Both render through the same error renderer,
and both carry `problem`, `fix` and `details`.

## Goals / Non-Goals

**Goals:**

- No part of a value refused for its shape reaches `problem`, `fix` or `details` of any `config set`, `config unset`
  or `config get` error.
- Each refusal still says what's wrong and where: the path, what it takes, and for unreadable JSON or YAML, the line,
  column and reason.

**Non-Goals:**

- Masking what config already holds when `config get` is asked for it.
- Changing the SDK's `PatternError` message, which runners use too: core builds its own words from the new `rule`
  field instead (D5). A runner refusing a malformed pattern in `run/start` is out of scope: config refuses it first,
  so none reaches a runner from troupe.
- Changing troupe's own files' error messages from `strict_json` (event store, artifacts): only a new field is added.

## Decisions

### D1. Never repeat the value, rather than repeat the part that can't be user info

The issue left the choice to the design: repeat nothing, or repeat what can't be user info. Repeat nothing.

- The person typed the value in the same command, so it's on their screen and in their shell history. Repeating it
  adds little for a typo. What helps is which path, and what that path takes, and both stay.
- Where a value has several assignments in one command, the path says which one was refused.
- Deciding what "can't be user info" is a guess about a value that's already malformed: #323 rejected stripping user
  info from a quoted endpoint for this reason (runtime-checks design D8). A bare token (`sk-…`) has no `@` at all.

*Alternative:* quote the value when it's short and has no `@`, `:` or `/`. Rejected: a password needs none of them.

### D2. Unreadable JSON says where and why, in words that hold no content

`StrictJSONError` gains `rule` (content-free words) and `line` and `column` (or none when unknown). From
`json.JSONDecodeError`, `rule` is its `msg` (`Expecting value`, `Unterminated string starting at`, …: the stdlib's
fixed messages never hold the document) and the position its `lineno` and `colno`. A repeated key's `rule` is "a key
appears more than once in one object", without the key, which is part of the value. NaN and Infinity keep their
names (fixed words). Bytes that aren't UTF-8 give "it isn't UTF-8" and the byte offset. `str(error)` stays as it is,
so troupe's own files' messages don't change.

The CLI's error: `the value for runtimes.box.endpoint isn't JSON: Expecting value (line 1, column 1).` `details`
holds `path`, `rule` (the words, no position) and `line` and `column`. The protocol's error schema closed
`config.invalid`'s details to `path` and `rule`, so it gains `line` and `column`: optional integers from 1, each
present only with the other, for a value given as JSON or YAML that couldn't be read (owner, 2026-11-11, found at
apply). They're additive, so every other `config.invalid` still validates; pre-1.0, no reader has to be kept
working anyway. Touching `protocol/` releases the protocol at its next version, which D6's description fix does
too.

*Alternative:* put the position only in the rule's words, leaving the protocol alone. Rejected: a later surface
would have to parse the rule to point at the column.

A value file in YAML is refused the same way, with ruamel's `problem_mark` for the position and none of its
message: its duplicate-key message quotes the repeated key's value.

*Alternative:* drop the reason and say only "isn't JSON". Rejected: the reason and column are what help with a typo
in a long JSON value, and they hold none of it.

### D3. Name a value only after it has passed its shape check, and only when the rule is about that name

Two refusals are about a name that has already passed a narrow shape check, and their fix is a command built from
it: a runner troupe doesn't know (it already matches the actor-name pattern), and a runtime config doesn't define
(it already matches the runtime name pattern, and the fix defines `runtimes.<name>`). These keep naming the value.

An `expect` path no effect covers was a third, until the review of #384 found its shape check (a theatre path) lets
`https://user:pw@example.com/x` through: only a narrow pattern makes naming safe. It's named by its position, like
an effect pattern (D5): "expect's item 2 isn't covered by a write or move effect", saying which list because a merge
conflict shows the rule under the actor. Its fix is the `troupe config set` that declares a covering pattern, holding
the write patterns the actor already has and a placeholder, `<a pattern covering item 2 of actors.tester.expect>`,
for the one to add (owner, 2026-11-11). The patterns it holds aren't being refused, and their own check refuses `:`,
so none carries a URL's user info. The person edits one placeholder instead of pasting a ready command.

Every other refusal of a value, which is a refusal of its shape, names none of it: the CLI's (D1), the `enum` rule
("it must be one of 'worktree', 'theatre' (the actor schema)"), the fallback for a rule with no description (D4),
an effect pattern the effects rules refuse (D5), and an `expect` path no effect covers.

The move fix (`_move_fix`) is a refusal of where options are, not of their shape, and its command rebuilds the
person's options so they lose nothing. It keeps doing so; its endpoint with user info is already `<url>` (#323).

*Alternative:* mask every value, names included. Rejected: "there's no runtime named '…'" and its fix
`troupe config set runtimes.nowhere.endpoint=<url>` would lose the one word that tells the person what to define,
for a value that has already been checked to be a name.

*Alternative:* keep naming effect patterns, as the effects spec required. Rejected (owner, 2026-11-11): a pattern is
named exactly when it fails its shape check, and `:` is one of the things that fails it, so a URL with a password
put in `effects.write` would be printed back.

### D4. Schema rules with no description are put in words

`_rule`'s fallback uses jsonschema's `error.message`, which begins with the instance. Replace it with words built
from the validator and its value, never the instance: `minLength` → "it must be at least N characters",
`minimum` / `exclusiveMinimum` / `maximum`, `minItems`, `uniqueItems` → "its items must differ", `const` → "it must
be X" (the schema's value, not the person's), `pattern` → "it doesn't fit the pattern P", `propertyNames`,
`not`, `oneOf` / `anyOf` with no description → "it doesn't fit {against}". Any validator not listed gives "it breaks
{against}'s {validator} rule". These are the validators the config and options schemas use today; a test walks the
schemas and fails when one uses a validator `_rule` has no words for, so a new one can't fall back to a message that
repeats the value.

### D5. Effect patterns are refused by position and rule, not by the pattern

`PatternError` gains `rule`: the words after the pattern (`is absolute; patterns are relative to the workspace`),
with its message unchanged, since runners use it too. Core builds the effect-pattern problem from the list, the
pattern's position in it and `rule`: `actors.tester.effects.write, item 1: it is absolute; patterns are relative to
the workspace. Runs get a scratch directory…`. The fix says to change or remove that item, without quoting it.
`details` holds the path to the item and the rule. The "the schema refused what the SDK accepts" branch says that
the item doesn't fit the actor schema's pattern, without the pattern.

### D6. A malformed path shows the text up to where reading failed

`_malformed` shows `text[: offset + 1]` in `problem` and `details.text`, and the whole text only when reading failed
at its end. Reading never passes an `=` outside brackets, so in `config set` nothing after the path's `=` is shown,
and a path given `=value` in `config unset` or `config get` is cut at the `=`. Inside a bracket it does pass one,
so a failure there (an escape at the end or an unknown escape) shows the text only up to that bracket's `[`, as an
unclosed bracket's error already did: `a[b=https://user:pw@h\x` shows `a[` (review of #384). The dot-before-bracket fix shows the
corrected text up to the end of that bracket (`a[b]`), not the rest. `details.offset` is unchanged. The error schema's description of `details.text` ("The
path as it was typed") is corrected to say it stops at the failing character.

*Alternative:* split `config set`'s argument at the first `=` before reading it. Rejected: a key in brackets may hold
`=` (`prices[a=b]`), which is why the reader decides where the path ends.

### D7. A key from inside a value is part of the value

Found by the review of #384. A group set with `--json` brings its own keys, and core named a key it refused: an
unknown field (`runtimes.box[https://user:pw@host]: there's no such field`), or a runtime or actor name that isn't
one. A key the person typed as part of the path is theirs to see named ("name the key"); a key inside the value is
part of the value.

Core can't tell them apart from the change's entries, since a group is flattened into one entry per leaf. So
config-set passes the request's operation paths to the check (`typed`). A key at a path no operation path reaches
came from inside a value. Such a key is never named: an unknown field is refused at the path the value was set at,
saying how many fields the schema doesn't define and listing those it does; a bad runtime or actor name is refused
at `runtimes` or `actors`. The options a runner moved to its runtime (`endpoint`, `model`) are troupe's own words,
and keep their move refusal.

A merge or a perform checks config no one just typed, and passes nothing: what config holds is named as before.
Keys a schema checks with `propertyNames` (model names under `prices`) are already refused at the map's path
without the key, and a key that passes is a name, as in D3.

*Alternative:* always name the parent path. Rejected: a misspelt field typed as a path (`actors.tester.runnr`)
would lose the name the person typed, which the config spec's "A misspelt field" scenario requires.

## Risks / Trade-offs

- [A person loses the echo they'd use to spot a typo] → The path, what it takes, and for JSON the column, stay; the
  value is on their own command line.
- [A new validator in a schema falls back to jsonschema's message] → D4's test fails when a schema uses a validator
  with no words.
- [A new CLI or core refusal adds `{value!r}` again] → The canary tests drive each refusal through the CLI; a property
  test feeds generated values holding a canary through `value_of` for each kind and asserts the canary never appears
  in the error's `problem`, `fix` or `details`.
- [Tests that assert the old echoed text] → Updated in the same commit (`test_cli_config.py` 207 and 332,
  `test_config_paths.py` 71, `test_config_kinds.py` 290).
- [A person can't see which pattern was refused in a long list] → The position names it; `config get` shows the list.
