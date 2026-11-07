# Spec Delta

## ADDED Requirements

### Requirement: A config path can put any key in brackets
A config path typed in a command SHALL be keys joined by dots, where any key MAY be written in square brackets instead,
with no dot before the bracket. Nothing inside brackets SHALL split the key. Inside brackets `\]` SHALL be a `]` and
`\\` a `\`. A bracketed key and the same key written plain SHALL be the same path.

#### Scenario: A model's name that holds a dot
- **WHEN** a person types the path `runtimes.openai.prices[gpt-4.1].input`
- **THEN** its keys are `runtimes`, `openai`, `prices`, `gpt-4.1` and `input`

#### Scenario: A plain path is unchanged
- **WHEN** a person runs `troupe config set actors.tester.runner=scripted`
- **THEN** the change has one entry, for the path `["actors", "tester", "runner"]`

#### Scenario: Brackets around a key that needs none
- **WHEN** a person runs `troupe config get actors[tester].runner`
- **THEN** it shows the same value as `troupe config get actors.tester.runner`

#### Scenario: Escapes inside brackets
- **WHEN** a person types the path `a[x\]y\\z]`
- **THEN** its keys are `a` and `x]y\z`

#### Scenario: A colon needs no brackets
- **WHEN** a person types the path `runtimes.ollama.prices.llama3:3b`
- **THEN** its keys are `runtimes`, `ollama`, `prices` and `llama3:3b`

### Requirement: Every config command reads a path the same way
`troupe config set` (including `<path>=@<file>`), `troupe config unset`, `troupe config get` and `troupe config get
--resolved` SHALL read a path with the same syntax. In `troupe config set`, the path SHALL end at the first `=` that
isn't inside brackets.

#### Scenario: Set at a bracketed key
- **WHEN** a person runs `troupe config set runtimes[my.rt].endpoint=http://localhost:9`
- **THEN** it is refused with `config.invalid` because `my.rt` isn't a runtime name, and the error's details hold the
  path `["runtimes", "my.rt"]`

#### Scenario: Unset a bracketed key
- **WHEN** a person runs `troupe config unset runtimes.openai.prices[gpt-4.1]`
- **THEN** the request it sends removes the path `["runtimes", "openai", "prices", "gpt-4.1"]`

#### Scenario: Get at a bracketed key
- **WHEN** a person runs `troupe config get runtimes[my.rt]` and nothing is set there
- **THEN** it says nothing is set at `runtimes[my.rt]`

#### Scenario: A key that holds an equals sign
- **WHEN** a person runs `troupe config set 'actors[a=b].runner=scripted'`
- **THEN** it is refused with `config.invalid` because `a=b` isn't an actor name, and the error's details hold the path
  `["actors", "a=b"]`

#### Scenario: A value from a file at a bracketed key
- **WHEN** a person runs `troupe config set runtimes[my.rt]=@runtime.json`
- **THEN** the file is read as the runtime's JSON, and the change is refused with `config.invalid` for the path
  `["runtimes", "my.rt"]`

#### Scenario: Resolved values for a bracketed runtime name
- **WHEN** a person runs `troupe config get --resolved runtimes[openai]`
- **THEN** it shows the runtime `openai`'s resolved values, as `troupe config get --resolved runtimes.openai` does

### Requirement: A config path is shown in the form it is typed
Wherever troupe shows a config path, in what a config command prints and in the problem and fix of an error, it SHALL
show it in the form a command reads. A key that holds `.`, `[`, `]`, `=` or `\` SHALL be shown in brackets, with `]`
and `\` escaped, and any other key plain. Reading a shown path SHALL give back the same keys.

#### Scenario: A plain key is shown plain
- **WHEN** a person runs `troupe config set actors[tester].runner=scripted`
- **THEN** standard output names the path as `actors.tester.runner`

#### Scenario: An entry at a key that holds a dot
- **WHEN** `troupe config set` or `troupe config unset` reports an entry for the path
  `["runtimes", "openai", "prices", "gpt-4.1", "input"]`
- **THEN** it names the path as `runtimes.openai.prices[gpt-4.1].input`

#### Scenario: An error from the core names a bracketed key
- **WHEN** a person runs `troupe config set runtimes[my.rt].endpoint=http://localhost:9`
- **THEN** the error's problem and fix name the runtime as `runtimes[my.rt]`

#### Scenario: A conflict at a key that holds a dot
- **WHEN** `troupe config get` reports a conflict at the path `["runtimes", "openai", "prices", "gpt-4.1", "input"]`
- **THEN** it names the path as `runtimes.openai.prices[gpt-4.1].input`

#### Scenario: Shown paths read back
- **WHEN** any path of non-empty keys, whatever characters they hold, is shown and the shown text is read as a path
- **THEN** the keys read are the keys shown

### Requirement: A malformed config path is refused
A config path that can't be read SHALL be refused with `config.path-malformed`, before anything is recorded. The
error SHALL name the text, the character position where reading failed, and the rule broken. Nothing about it SHALL
be guessed or skipped.

#### Scenario: An unclosed bracket
- **WHEN** a person runs `troupe config unset runtimes.openai.prices[gpt-4.1`
- **THEN** it is refused with `config.path-malformed`, naming the text and saying the `[` has no closing `]`

#### Scenario: An escape at the end
- **WHEN** a person types the path `a[b\`
- **THEN** it is refused with `config.path-malformed`, saying the `\` escapes nothing

#### Scenario: An unknown escape
- **WHEN** a person types the path `a[b\.c]`
- **THEN** it is refused with `config.path-malformed`, saying inside brackets only `\]` and `\\` are escapes

#### Scenario: A backslash outside brackets
- **WHEN** a person types the path `runtimes.openai.prices.gpt-4\.1.input`
- **THEN** it is refused with `config.path-malformed`, and the fix says to put a key that holds a dot in brackets,
  such as `[gpt-4.1]`

#### Scenario: An empty key
- **WHEN** a person types the path `actors..runner`, `actors.`, `.actors`, `a[]` or nothing at all
- **THEN** it is refused with `config.path-malformed`, saying a key can't be empty

#### Scenario: Text straight after a bracket
- **WHEN** a person types the path `a[b]c`
- **THEN** it is refused with `config.path-malformed`, saying a `]` is followed by `.`, `[` or the end

#### Scenario: A dot before a bracket
- **WHEN** a person types the path `a.[b]`
- **THEN** it is refused with `config.path-malformed`, and the fix says to write `a[b]`

#### Scenario: A stray closing bracket
- **WHEN** a person types the path `a]b`
- **THEN** it is refused with `config.path-malformed`, saying the `]` closes no `[`

#### Scenario: The error is structured data
- **WHEN** a malformed path is refused
- **THEN** the error validates against the protocol's error schema, its details holding the text, the position and
  the rule
