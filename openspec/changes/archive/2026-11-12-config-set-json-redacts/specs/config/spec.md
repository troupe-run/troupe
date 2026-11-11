## ADDED Requirements

### Requirement: A refused config value is repeated nowhere
When `config set`, `config unset` or `config get` refuses a value for its shape, no error, notice, client message or
standard error SHALL hold any part of the value. The error SHALL name the path and what the path takes. A value
SHALL be named only when it has passed its shape check and the rule is about that name: an unknown runner or a
runtime config doesn't define.

#### Scenario: JSON that isn't JSON
- **WHEN** a person runs `troupe config set --json runtimes.box.endpoint=https://user:<canary>@example.com/v1`
- **THEN** it is refused with `config.invalid`, naming `runtimes.box.endpoint` and where the JSON stopped making sense,
  and neither the standard error nor the client message holds the canary or `example.com`

#### Scenario: A value that isn't the path's type
- **WHEN** a person sets a boolean, a number, a list or group, or a path with no single type to text holding a canary
- **THEN** it is refused with `config.invalid`, naming the path and what it takes, and neither the standard error nor
  the client message holds the canary

#### Scenario: A value file that isn't JSON or YAML
- **WHEN** a person runs `troupe config set actors.tester.options=@options.yaml` and the file's broken line holds a
  canary
- **THEN** it is refused with `config.invalid`, naming the file, the line and the column, and neither the standard
  error nor the client message holds the canary

#### Scenario: A value outside the schema's list
- **WHEN** a person sets `actors.tester.workspace` to a canary
- **THEN** it is refused with `config.invalid`, naming the path and the values it takes, and neither the standard
  error nor the client message holds the canary

#### Scenario: A malformed path before a value
- **WHEN** a person runs `troupe config set runtimes.box.endpoint.=https://user:<canary>@example.com/v1`
- **THEN** it is refused with `config.path-malformed`, and neither the standard error nor the client message holds
  the canary

#### Scenario: A value given to unset or get
- **WHEN** a person runs `troupe config unset` or `troupe config get` with `runtimes.box.endpoint=https://user:<canary>@example.com/v1`
- **THEN** it is refused with `config.path-malformed`, and neither the standard error nor the client message holds
  the canary

#### Scenario: A value typed after a space instead of an =
- **WHEN** a person runs `troupe config set runtimes.box.endpoint https://user:<canary>@example.com/v1`
- **THEN** it is refused with `config.invalid`, saying which `path=value` has no `=` by its position, and neither the
  standard error nor the client message holds the canary

#### Scenario: A key inside a JSON group
- **WHEN** a person runs `troupe config set --json 'runtimes.box={"https://user:<canary>@example.com": 1}'`
- **THEN** it is refused with `config.invalid`, naming `runtimes.box` and the fields a runtime defines, and neither
  the standard error nor the client message holds the canary

#### Scenario: A key typed as a path is still named
- **WHEN** a person sets `actors.tester.runnr`
- **THEN** it is refused, naming `actors.tester.runnr` and saying there's no such field

#### Scenario: A name is still named
- **WHEN** a person sets `actors.tester.runtime=nowhere` and config defines no runtime `nowhere`
- **THEN** it is refused, naming `nowhere` and the command that defines it

## MODIFIED Requirements

### Requirement: Command-line values are typed by the schema
The CLI SHALL type a value by the schema at its path: a string as given, an integer, number or boolean parsed
strictly, and an array as JSON. Where the schema doesn't give one type, the value SHALL be refused unless it is
given as JSON with `--json`, naming the path. A refusal SHALL NOT repeat the value.

#### Scenario: A number for a string field
- **WHEN** a person sets a string field to `3`
- **THEN** the value is the string `"3"`

#### Scenario: A boolean that isn't one
- **WHEN** a person sets a boolean field to `yes`
- **THEN** it is refused, naming the path and saying to write `true` or `false`, without repeating `yes`

#### Scenario: JSON that isn't JSON
- **WHEN** a person runs `troupe config set --json` with a value that isn't JSON
- **THEN** it is refused, naming the path, the line and column where the JSON stopped making sense and why, without
  repeating any of the value, and its details hold the path, the rule, the line and the column

### Requirement: A malformed config path is refused
A config path that can't be read SHALL be refused with `config.path-malformed`, before anything is recorded. The
error SHALL name the text up to where reading failed, or up to the `[` of a bracket it failed inside, the character
position where reading failed, and the rule broken. It SHALL NOT show the text after that, which in `config set` can
hold the value. Nothing about it SHALL be guessed or skipped.

#### Scenario: An unclosed bracket
- **WHEN** a person runs `troupe config unset runtimes.openai.prices[gpt-4.1`
- **THEN** it is refused with `config.path-malformed`, naming the text up to the `[` and saying the `[` has no closing
  `]`

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
- **THEN** the error validates against the protocol's error schema, its details holding the text up to where reading
  failed, the position and the rule

#### Scenario: A value inside a bracket left open
- **WHEN** a person runs `troupe config set 'a[b=https://user:<canary>@example.com\x'`
- **THEN** it is refused with `config.path-malformed`, saying inside brackets only `\]` and `\\` are escapes, and the
  error shows the text only up to the `[`

#### Scenario: The value after a malformed path
- **WHEN** a person runs `troupe config set 'a]b=<canary>'`
- **THEN** it is refused with `config.path-malformed`, saying the `]` closes no `[`, and the error holds none of the
  text after the `]`
