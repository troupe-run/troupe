# Proposal

## Why

`troupe config set` splits a path at every dot (`troupe.cli.values.split_path`), so it can't address a key that holds
one. Model names often do (`gpt-4.1`, `llama3.2:3b`), and #292 (change `estimated-cost`, design D5) prices models
under `runtimes.<name>.prices.<model>`. Until this is fixed, one model's price can only be set by replacing the whole
`prices` map as JSON or from a file. The owner accepted that limit in #292 and raised troupe#303 to lift it
(2026-11-07).

## What Changes

- A config path can put any key in square brackets, and nothing inside the brackets splits:
  `runtimes.openai.prices[gpt-4.1].input`. Inside brackets, `\]` is a `]` and `\\` is a `\`. A plain key that holds
  none of `[`, `]`, `\` or `=` reads as it did before (`actors.tester.runner`). Brackets were chosen over double
  quotes or backslash escapes (owner, 2026-11-07, on troupe#303) because no shell quietly strips them. Unquoted
  quotes and backslashes are removed by bash and zsh, and Windows PowerShell 5.1 drops embedded quotes. Either leaves
  a valid but different path, with no error.
- The same syntax is used everywhere a config path is typed: `config set` (including `<path>=@<file>`), `config
  unset`, `config get` and `config get --resolved`. In `config set`, the path ends at the first `=` outside brackets,
  so a key may hold `=`.
- Every place troupe shows a config path uses the same form, so a shown path can be copied back into a command. That
  covers what `config set`/`unset` print, conflicts, and the problems and fixes of config errors from the core. A key
  that holds `.`, `[`, `]`, `=` or `\` is shown in brackets. Any other key is shown plain.
- A malformed path is refused with a new error, `config.path-malformed`, naming the text, where it went wrong and the
  rule. That covers an unclosed `[`, a trailing or unknown escape, an empty key, text straight after a `]`, `.[`, a
  stray `]`, and a backslash outside brackets (the Helm habit `gpt-4\.1`, which would otherwise split quietly).
  **BREAKING** (pre-1.0, nothing outside this repository reads it): a path with an empty key, such as `a..b`, is now
  refused with `config.path-malformed` instead of `config.invalid`. And a key that holds `[`, `]`, `\` or `=` must now
  be written in brackets: the old reader took any text between dots as a key, so `config unset a=b` or `x]y` is now
  refused, and `prices.foo[1]` now reads as the keys `prices`, `foo` and `1`.
- Parsing and showing paths live in one place in the core, which the CLI uses. The core's requests still carry a path
  as an array of keys, so the client protocol's messages don't change. Only the error catalogue gains a code.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `config`: adds requirements for how a config path is written, typed and shown (brackets for any key, the same form
  in every command and every message), and for refusing a malformed path.

## Impact

- **Code:** a new path module, `troupe.core.config_paths` (parse and show), beside `strict_json` because the CLI
  may not import `troupe.core.config` (design D3). It replaces `troupe.core.config.changes.dotted`, which is removed,
  in every message in `kinds.py`, `merge.py`, `changes.py` and `commands.py` (`config.not-resolvable`).
  `troupe.cli.values` (`split_path`, `_usage`) and `troupe.cli.config` (assignments, entry and conflict lines,
  `_runner_of`) switch to it.
- **Protocol:** `error.schema.json` gains `config.path-malformed` and its details, in `protocol/schemas/` and the
  copy shipped in the package. Its exit code goes in the core's table.
- **Docs:** `docs/prompt-book/cli.md` (how a path is written), `contributing/config.md` (the new code), and the
  dotted-path limit note #292 adds to `docs/stagecraft/runtimes.md`, if #292 has merged by then.
- **Specs:** `config` only. No spec is added or removed, and no Purpose changes, so infrastructure's
  `oob/troupe-spec-purposes.json` is untouched.
- **Not in scope:** the shape of `prices` (#292). Shell-quoting the commands shown in fixes. A bracketed path needs
  quoting in zsh, which refuses it loudly if it isn't.
