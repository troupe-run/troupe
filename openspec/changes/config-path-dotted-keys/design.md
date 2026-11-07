# Design

## Context

See proposal.md for why. What the code does now:

- The core's requests (`config-set`, `config-get`) already carry a path as an array of keys, and every error's
  `details.path` is an array too. Only the text form is the problem.
- **Reading.** `troupe.cli.values.split_path` splits at every `.`, and refuses an empty key with `config.invalid`.
  `troupe.cli.config._assignments` splits `path=value` at the first `=` (`str.partition`). `_runner_of` compares the
  typed text with `f"actors.{actor}.runner"`. `values._usage` and `_assignments` work out `details.path` with
  `text.split(".")`.
- **Showing.** `troupe.core.config.changes.dotted` is `".".join(path)`. It's used for every problem and fix in
  `kinds.py`, `merge.py` (conflict messages) and `changes.py` (null values). `commands.py` (`config.not-resolvable`)
  and `cli/config.py` (entry lines, conflict lines) do their own `".".join`. `config get` echoes the typed text in
  "Nothing is set at …".
- Today no config key can hold a dot: actor and runtime names are `^[a-z][a-z0-9-]{0,63}$`. The first keys that can
  are #292's model names under `runtimes.<name>.prices`, which allow any character but control characters
  (`protocol/schemas/runtime.schema.json`). So tests that need a dotted key to reach the core use a refused name
  (`runtimes[my.rt]`), and the error's `details.path` shows what the parse produced.

## Goals / Non-Goals

**Goals:**
- One reader and one writer for the text form, in one module, that every surface uses.
- Reading what's shown always gives back the same keys, which a property test checks.

**Non-Goals:**
- Changing the client protocol's path type or any message other than the error catalogue.
- Shell-quoting the commands shown in fixes (see Risks).
- Accepting more than one way to write a key that needs brackets.

## Decisions

### D1. Brackets, with `\]` and `\\` as the only escapes

Owner's choice, 2026-11-07, on troupe#303, from these options:

- *Double quotes* (`prices."gpt-4.1"`, like TOML and jq): unquoted, bash and zsh strip them, and Windows PowerShell 5.1
  drops embedded `"` when it passes an argument to a native `.exe`. Either way the text that arrives is
  `prices.gpt-4.1`, a valid path that splits, with no error.
- *Backslash escapes* (`gpt-4\.1`, like Helm and kubectl): unquoted, bash and zsh strip the `\`, with the same silent
  split.
- *Both*: a bigger grammar, and both forms can still be lost silently.
- **Brackets**: no shell strips them. Unquoted in zsh they're a glob that fails loudly ("no matches found"). bash
  passes an unmatched glob through as typed, and PowerShell and cmd don't treat them specially.

Inside brackets, any character is literal except `\` and `]`. `\]` is `]` and `\\` is `\`. Any other `\x`, or a `\`
at the end, is malformed rather than taken literally, so the escapes can be added to later without changing what an
existing path means.

### D2. The grammar is strict, with one written form per key that needs brackets

```
path    = segment *( "." plain / "[" bracket "]" )
segment = plain / "[" bracket "]"
plain   = 1*( any character except . [ ] = \ )
bracket = 1*( any character except ] \  /  "\]"  /  "\\" )
```

Refused, each with its own rule text and the character position where reading failed:

| Text | Rule |
|---|---|
| `a..b`, `a.`, `.a`, `a[]`, empty | a key can't be empty |
| `a[b` | the `[` at N has no closing `]` |
| `a[b\` | the `\` at N escapes nothing |
| `a[b\.c]` | inside brackets only `\]` and `\\` are escapes |
| `a.b\c` | a backslash only escapes inside brackets. The fix says to write the key in brackets |
| `a[b]c` | a `]` is followed by `.`, `[` or the end |
| `a.[b]` | no dot before a `[`. The fix says to write `a[b]` |
| `a]b` | the `]` at N closes no `[` |
| `a=b` (outside `config set`'s split) | a key holding `=` is written in brackets |

`a.[b]` isn't ambiguous, and accepting it would be easy. It's refused anyway so that each path has exactly one written
form, which is what the round trip and the error messages show. It's easy to loosen later. Refusing a `\` outside
brackets catches the Helm habit (`gpt-4\.1`). Taken literally, it would split into `gpt-4\` and `1`, with no error.
Plain keys can't hold `=` so that `config set`'s split (D4) and the reader agree on where a path ends, whichever
command reads it.

A whitespace or non-ASCII key is plain. The reader reads whatever reaches it in argv, and quoting for the shell is the
person's job, as it is for values.

### D3. One module in the core: `troupe.core.config_paths`

`parse(text) -> tuple[str, ...]` and `shown(path) -> str`, with `parse(shown(p)) == p` for every path of non-empty
keys. `shown` brackets a key that holds `.`, `[`, `]`, `=` or `\`, escaping `\` and `]`. Any other key is plain. An
empty key, which no parsed path has, is shown as `[]` so a stray one is visible rather than hidden. It doesn't read
back, which is correct, because it can't be addressed.

It goes in the core, not the CLI, because the core writes paths into problems and fixes and must write them in the
form the CLI reads. A later surface (the run server, a UI) that takes text paths reads them with the same function.
`changes.dotted` is removed and its call sites use `shown`, so there's one name for one rule. Every `".".join(path)`
over config keys in `core/config/commands.py` and `cli/config.py` moves to it.

It sits beside `troupe.core.strict_json` and `troupe.core.schemas`, not inside `troupe.core.config`. The import
contract "the CLI reaches runs and config only through the client protocol" forbids the CLI importing
`troupe.core.config`, and the CLI must read paths. The module holds only the text form of a path, no config
behaviour, so it doesn't open a way round the protocol. This was found at apply, when the contract refused the first
placement (`troupe.core.config.paths`). Loosening the contract was the alternative, and it's worse.

The alternative was to keep parsing in the CLI (`values.split_path`) and only fix the showing in the core. That puts
one grammar in two places, which is exactly what the "one named place" rule exists to stop.

### D4. `config set` finds the end of the path with the reader

`_assignments` no longer partitions at the first `=`. The reader reads the path from the start of the argument and
stops at the first `=` outside brackets (`parse_prefix(text) -> (keys, end)`). Text with no such `=` keeps its
current error ("doesn't set anything"). When the text can't be read as a path, the `config.path-malformed` error comes
first. `_runner_of` compares parsed paths (`path == ("actors", actor, "runner")`, on the tuple of keys), so `actors[tester].runner=…`
counts as setting the runner too. `value_of` takes the parsed keys rather than the text.

### D5. A new error code, `config.path-malformed`, exit 1

Its details are `{"text": <as typed>, "offset": <0-based character index>, "rule": <rule text>}`, all required and
closed, added to `error.schema.json` in `protocol/schemas/` and the package's copy. The problem names the text and the
rule, and the fix says how to write it (brackets, or `a[b]`).

- *Why not `config.invalid`*: its `details.path` is an array of non-empty keys. A path that can't be read has no keys,
  so the current code puts in either the raw text or a lossy split (`a..b` → `["a", "b"]`), which misstates the
  input.
- *Exit 1, not 2*: `config.invalid` exits 1 today for the same input, and the CLI spec ties exit 2 to the `usage.*`
  shapes, which name the command and point at its help. The core's reader doesn't know the command.
- **BREAKING**, pre-1.0: `a..b` moves from `config.invalid` to `config.path-malformed`. No records hold it (it's an
  error, not an event), and nothing outside this repository reads it.

`contributing/config.md`'s code table gains the row, and a test raises the code (protocol_guard fails a catalogued
code that's never raised).

### D6. Tests

- A property test (hypothesis): for any path of non-empty keys drawn from all of Unicode, without surrogates,
  `parse(shown(p)) == p`, and `shown` of a path whose keys hold none of `.[]=\` equals `".".join(p)`. The second
  property is the differential check against today's behaviour for every path that worked before.
- A property test over arbitrary text: `parse` either returns keys or raises `config.path-malformed`, never anything
  else, and any text with no `[`, `]`, `\` or `=` parses exactly as `text.split(".")` did whenever no key is empty
  (the old reader's accepted set is unchanged).
- A table test with one row per refusal in D2, checking the rule, the offset and that the error validates against
  the schema.
- CLI tests for each spec scenario, end to end where a key can reach the core today, and rendering tests with result
  data for entries and conflicts at a dotted key (D3's context: no such key exists in config until #292).

## Risks / Trade-offs

- [A bracketed path typed unquoted in zsh fails with "no matches found"] → it fails loudly, never silently. The docs
  show the bracketed form quoted (`'runtimes.openai.prices[gpt-4.1].input=2'`), and say why.
- [Fixes that show a command (`Unset runtimes[my.rt]…`, `troupe config set <path>='…'`) aren't shell-quoted around
  the path] → a pasted fix with brackets fails loudly in zsh and works in bash and PowerShell. Shell-quoting is
  per-shell, and errors are structured data that each surface phrases. Not quoting is deliberate here, and it can be
  revisited.
- [#292 and this change both touch `docs/stagecraft/runtimes.md`] → whichever merges second updates #292's
  dotted-path limit note to the bracket form (tasks 5.3). Neither waits on the other.
- [`shown` is used in messages that tests match exactly] → only keys that hold `.[]=\` change form, and no such key
  can exist in config today. So existing message tests keep passing unchanged, and that is itself a check (D6).

## Migration Plan

None needed. The core's paths are arrays and unchanged, and no event or file stores the text form. Rolling back is
reverting the change.
