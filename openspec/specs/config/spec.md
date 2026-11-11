# config Specification

## Purpose

Capability: `cap:config`

Holds a theatre's config as events with lineage, works out the config every command uses from them, including
across merged branches, and defines the actor, the first kind of config.

## Requirements

### Requirement: Config is read only from its events
troupe SHALL work out config only from the theatre's config events. It SHALL NOT read a config file's content to
decide what config holds.

#### Scenario: A file edited by hand doesn't change config
- **WHEN** a person changes `runner` in `.troupe/actors/tester.yaml` by hand, and runs `troupe config get
  actors.tester.runner`
- **THEN** it shows the runner the config events set
- **AND** the edited file is refused when it is next flushed

### Requirement: One stream per theatre
A theatre's config events SHALL be one stream, with the same id in every theatre.

#### Scenario: Two actors share one stream
- **WHEN** a person sets a value of `tester` and then a value of `reviewer`
- **THEN** both changes are events in the same stream, the second following the first

### Requirement: A command records one change
Each command that changes config SHALL record exactly one `Config.Changed` event, however many values it changes.
Separate commands SHALL NOT be combined into one event. A command that would change nothing SHALL record nothing
and say so.

#### Scenario: Several values in one command
- **WHEN** a person runs `troupe config set actors.tester.runner=scripted actors.tester.expect='["out/hello.txt"]'`
- **THEN** one `Config.Changed` is recorded, with an entry for each of the two values

#### Scenario: Two commands in a row
- **WHEN** a person runs `troupe config set` twice, with nothing in between
- **THEN** two `Config.Changed` events are recorded, each with its own change id and lineage

#### Scenario: Setting a value to what it already is
- **WHEN** a person sets `actors.tester.runner` to the runner it already has
- **THEN** nothing is recorded, and the command says nothing changed

### Requirement: A change entry holds the path, the old value's hash and the new value
Each entry in a `Config.Changed` SHALL hold the value's path as an array of keys, `before` as `sha256:` and the
SHA-256 of the old value's canonical JSON, and `after` as the new value. `before` SHALL be absent when the value
didn't exist, and `after` absent when it was removed. Neither SHALL be null.

#### Scenario: A changed value
- **WHEN** `actors.tester.runner` changes from `scripted` to `claude-code`
- **THEN** the entry's path is `["actors", "tester", "runner"]`, its `before` is the hash of `"scripted"`, and its
  `after` is `"claude-code"`

#### Scenario: A new value
- **WHEN** `actors.tester.character` is set for the first time
- **THEN** its entry has an `after` and no `before`

#### Scenario: The same canonical form as event ids
- **WHEN** a value's `before` is compared with the hash of the value as recorded in an earlier `after`
- **THEN** they are equal, for strings, numbers, booleans and arrays alike

### Requirement: Objects are groups, and every other value is whole
An object in config SHALL be a group of values, and a path into it SHALL name one of its values. A string, number,
boolean or array SHALL be one value, replaced and compared as a whole, never merged inside (#135). An entry's
`after` SHALL never be an object.

#### Scenario: Setting a value inside a group
- **WHEN** a person sets `actors.tester.options.script` to a list of steps
- **THEN** the change has one entry, for the path `["actors", "tester", "options", "script"]`, whose `after` is the
  whole list

#### Scenario: A value that is an object
- **WHEN** a person tries to set `actors.tester.runner` to a JSON object
- **THEN** it is refused, naming the path and saying an object is a group of values

### Requirement: A group is removed as one entry
Removing a group SHALL be one entry addressed to the group, whose `before` is the hash of the group's canonical JSON
and which has no `after`.

#### Scenario: Removing an actor
- **WHEN** a person runs `troupe config unset actors.tester`
- **THEN** one change is recorded, with one entry for the path `["actors", "tester"]` and no `after`
- **AND** `tester` is no longer in config

### Requirement: A group can be set whole from a file
Setting a group from a file SHALL replace the whole group in one change, with an entry for each value added, changed
or removed under it.

#### Scenario: Setting an actor from a file
- **WHEN** `tester` has `runner` and `options`, and a person sets `actors.tester` from a file holding `runner` and
  `expect`
- **THEN** one change is recorded, setting `expect`, setting `runner` if it differs, and removing `options`

### Requirement: Values are checked before a change is recorded
A change SHALL be refused, recording nothing, when the config it would make fails its kind's schema or, for an
actor, when its options fail its runner's published options schema. The error SHALL name the path and the rule.

#### Scenario: A misspelt field
- **WHEN** a person sets `actors.tester.runnr`
- **THEN** it is refused, naming the path and saying the actor has no such field
- **AND** nothing is recorded

#### Scenario: Options the runner doesn't define
- **WHEN** a person sets `actors.tester.options.speed` for the scripted runner
- **THEN** it is refused, naming the path and the scripted runner's options schema

### Requirement: A merge combines each line's net change
When the config stream has more than one head, config SHALL be worked out from both lines of history: for each
value, each line's net change since the lines split, from its first `before` to its last `after`. A line whose net
change ends where it began SHALL count as not changing the value. A line whose first changes to the value start from
different values SHALL count as changing it.

#### Scenario: Two branches change different actors
- **WHEN** one branch sets a value of `reviewer`, another sets a value of `tester`, and they are merged
- **THEN** config holds both changes, with no conflict

#### Scenario: A change and a change back
- **WHEN** one branch changes `tester`'s character and changes it back, another changes it to new text, and they
  are merged
- **THEN** config holds the new text, with no conflict

#### Scenario: Two branches make the same change
- **WHEN** two branches each set `actors.tester.runner` to `claude-code`, and are merged
- **THEN** config holds `claude-code`, with no conflict

#### Scenario: Every clone agrees
- **WHEN** the same branches' events reach two clones in different orders
- **THEN** both clones work out the same config and the same conflicts

#### Scenario: A line whose first changes start from different values is a change
- **WHEN** one branch changes `tester`'s character from new text to other text, and another line of history holds two
  concurrent changes to it, one from that new text and one from another value, which a settle joins, and the line
  ends at the new text
- **THEN** the two lines are in conflict, whatever order the events arrived in

### Requirement: The history before the lines works out a value no line's change is left at
Where no line's change is left at a value, because the lines conflict or every one counts as not changing it, the
history before those lines SHALL work the value out by the same rule, never the order the events arrived in.

#### Scenario: A conflict after a settle shows the value the settle left
- **WHEN** two branches set `tester`'s character, one changing it to new text and the other changing it to other text
  and back, a write settles them, and two branches from the settle then set it to different text
- **THEN** the two later changes are in conflict, and config shows the new text the settle left, whatever order the
  events arrived in

#### Scenario: Lines after a settle that change a value back leave the value the settle left
- **WHEN** two branches set `tester`'s character, one changing it to new text and the other changing it to other text
  and back, a write settles them, and two branches from the settle each change it and change it back
- **THEN** config holds the new text the settle left, with no conflict, whatever order the events arrived in

### Requirement: Differing net changes to a value are a conflict between whole changes
Two lines whose net changes set one value to different things SHALL be in conflict. A conflict SHALL name each
conflicting change whole: its change id, who made it, when, and every entry in it.

#### Scenario: A window moved on one branch and narrowed on another
- **WHEN** one branch's change sets `min` from 0 to 5 and `max` from 10 to 15, another's sets `min` from 0 to 2, and
  they are merged
- **THEN** the two changes are in conflict
- **AND** the conflict shows both changes whole, including the first change's `max`

#### Scenario: A group removed on one branch and changed on another
- **WHEN** one branch removes `tester` and another changes `tester`'s character, and they are merged
- **THEN** the two changes are in conflict

### Requirement: A merged config that fails validation is a conflict
When the merged config fails its kind's schema, or an actor's options fail its runner's options schema, the changes
since the split that touched what failed SHALL be in conflict, even when no single value conflicts.

#### Scenario: Options that no longer suit the runner
- **WHEN** one branch changes `tester`'s runner, another changes options that only the old runner defines, and they
  are merged
- **THEN** the two changes are in conflict, naming the actor and the options schema it fails

### Requirement: Any conflict blocks config
While config has any conflict, every command that uses config SHALL refuse with `config.conflict`, listing each
conflict and the fix, except `config get` and a change that resolves every conflict.

#### Scenario: Perform with a conflict elsewhere
- **WHEN** config has a conflict on `tester` and a person runs `troupe perform reviewer`
- **THEN** it is refused with `config.conflict`, naming the conflict on `tester`

#### Scenario: Config get shows the conflict
- **WHEN** config has a conflict and a person runs `troupe config get`
- **THEN** it shows the config with each conflict and both sides' changes

### Requirement: A change resolves conflicts by setting every conflicting value
A change recorded while config has conflicts SHALL be accepted only if it sets or unsets every conflicting value, and SHALL
be accepted when it changes other values too. One that leaves a conflict SHALL be refused, naming what's left.

#### Scenario: Resolving a window
- **WHEN** a person resolves a conflict on `min` with `troupe config set …min=4 …max=14`
- **THEN** the change is recorded, config has no conflict, and lineage records who resolved it

#### Scenario: A change that resolves nothing
- **WHEN** config has a conflict on `tester` and a person sets a value of `reviewer` only
- **THEN** it is refused with `config.conflict`, naming the conflict left

### Requirement: Settling a fork is recorded with the next write
Reading a forked config stream SHALL record nothing. The next change recorded to it SHALL be preceded, in the same
batch, by a settling event whose parents are every head and whose state is the merged config.

#### Scenario: A read after a merge
- **WHEN** two branches' config changes are merged and a person runs `troupe config get`
- **THEN** no event is recorded

#### Scenario: The first write after a merge
- **WHEN** a person then runs `troupe config set`
- **THEN** one batch records a settling event naming both heads, then the change
- **AND** the stream has one head

### Requirement: An actor is defined by its runner, options, effect check and character
An actor SHALL have a `runner` (required), `options` (an object, default empty), an optional `effects` (what its runs
may change, spec: effects), `expect` (required: theatre-relative paths the run must create or change, where an empty
list means no file has to change), an optional `character` (text), an optional `workspace`: `worktree` (the
default when it's absent) or `theatre`, and optional `runtime` and `model` (spec: runtimes). Its name SHALL match
the client protocol's actor-name pattern.

#### Scenario: An actor with no effect check written
- **WHEN** a person sets only `actors.tester.runner`
- **THEN** it is refused, saying `expect` is required and that `[]` means no file has to change

#### Scenario: An effect check path outside the theatre
- **WHEN** a person sets `actors.tester.expect` to `["../elsewhere.txt"]`
- **THEN** it is refused, naming the path

#### Scenario: An actor name that doesn't fit
- **WHEN** a person sets `actors.Tester.runner`
- **THEN** it is refused, naming the name and the pattern

#### Scenario: Running in place
- **WHEN** a person runs `troupe config set actors.tester.workspace=theatre`
- **THEN** `tester`'s runs work in the theatre

#### Scenario: A workspace that doesn't exist
- **WHEN** a person sets `actors.tester.workspace` to `sandbox`
- **THEN** it is refused, naming the path, `sandbox`, and the accepted values `worktree` and `theatre`

#### Scenario: An effect the actor schema doesn't define
- **WHEN** a person sets `actors.tester.effects.network`
- **THEN** it is refused, naming the path and the effects `write`, `delete` and `move`

#### Scenario: An actor on a runtime
- **WHEN** a person runs `troupe config set actors.tester.runner=scripted actors.tester.expect=[]
  actors.tester.runtime=ollama actors.tester.model=llama3.2`
- **THEN** `tester`'s runs use the runtime `ollama` with the model `llama3.2`

### Requirement: Config commands
`troupe config set <path>=<value>…` SHALL set values, with `<path>=@<file>` reading a value from a file;
`troupe config unset <path>…` SHALL remove values or groups; and `troupe config get [<path>]` SHALL show the merged
config, or the value or group at a path, and with `--resolved`, a runtime's resolved values (spec: runtimes). A change
SHALL accept `--reason`, recorded in its lineage.

#### Scenario: A character from a file
- **WHEN** a person runs `troupe config set actors.tester.character=@tester-character.md`
- **THEN** the character is that file's text exactly

#### Scenario: A reason
- **WHEN** a person runs `troupe config set actors.tester.runner=scripted --reason "offline tests"`
- **THEN** the change's lineage records the reason

#### Scenario: Resolved runtimes
- **WHEN** a person runs `troupe config get --resolved`
- **THEN** it shows every runtime, built-in or in config, with each value's source

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

### Requirement: Config's types are generated from its schemas
troupe's types for config SHALL be generated from the config schemas in `protocol/`, and the quality check SHALL fail
when they aren't what the schemas generate. Each type SHALL accept exactly what its schema accepts.

#### Scenario: A schema changed without its types
- **WHEN** a field is added to `actor.schema.json` and the types aren't regenerated
- **THEN** `scripts/check.py` fails, naming the generated file and the command that regenerates it

#### Scenario: Types and schemas agree
- **WHEN** generated inputs and near misses (unknown keys, wrong types, values outside a pattern) are checked by both
  a type and its schema
- **THEN** both accept or both refuse each one

### Requirement: An audition records one change, like any other
`troupe init --audition` SHALL record exactly one `Config.Changed` defining the example actor, with lineage like any
config change, checked against the actor schema, the effects rules and its runner's options schema before it is
recorded. Plain `troupe init` SHALL record no config event.

#### Scenario: One change for the actor
- **WHEN** a person runs `troupe init --audition`
- **THEN** the config stream holds one `Config.Changed`, whose entries set `actors.lead`'s runner, options, effects,
  `expect` and, for Claude Code, its character
- **AND** its lineage names who ran it, via `cli`, with a command cause whose id is its change id

#### Scenario: Plain init records nothing
- **WHEN** a person runs `troupe init`
- **THEN** the config stream holds no event

#### Scenario: The audition's config is valid
- **WHEN** the example actor for each runner troupe has is checked against the actor schema, the effects rules and
  that runner's published options schema
- **THEN** it is valid

### Requirement: An audition needs an identity before it makes anything
`troupe init --audition` SHALL work out who is acting before it makes `.troupe/`. When there is no identity, it SHALL
fail as recording any change does, and SHALL make nothing.

#### Scenario: No identity
- **WHEN** no identity source gives an identity and a person runs `troupe init --audition`
- **THEN** it fails with the identity error, and no `.troupe/` is made

### Requirement: The Claude Code audition can edit files on a small budget
The Claude Code example actor SHALL have `runner: claude-code`, options with `maxBudgetUsd` of 1 and `allowedTools`
holding `Read`, `Glob` and `Grep`, `effects` with `write: ["**"]`, an empty `expect`, and a short character. It SHALL
leave `permissionMode` and `workspace` unset, so its runs work in a worktree and Claude Code can change only what its
effects declare.

#### Scenario: The Claude Code actor's file
- **WHEN** a person runs `troupe init --audition`
- **THEN** `.troupe/actors/lead.yaml` holds runner `claude-code`, those options, `effects.write: ["**"]` and
  `expect: []`, and no `workspace`
- **AND** `.troupe/actors/lead.md` holds the character, which is non-empty text

#### Scenario: Any direction can succeed
- **WHEN** the Claude Code example actor is performed with a direction that changes no file, or only edits files, and
  Claude Code reports success
- **THEN** the run ends `succeeded`, because no file has to change and every change is declared

### Requirement: The scripted audition runs offline and checks its effect
The scripted example actor SHALL have `runner: scripted`, an inline script that writes one file and reports success,
`effects` with `write` naming that file, and an `expect` naming it too. It SHALL have no character and leave
`workspace` unset.

#### Scenario: The scripted actor offline
- **WHEN** a person runs `troupe init --audition --runner scripted`, commits, allows the local stage and runs the
  printed `troupe perform lead`, with no network
- **THEN** the run ends `succeeded`, with its effect check passed on the file the script wrote and its audit passed

#### Scenario: No character for a runner that doesn't read one
- **WHEN** a person runs `troupe init --audition --runner scripted`
- **THEN** no `.troupe/actors/lead.md` is written

### Requirement: The Ollama audition can edit files with a small local model
The Ollama example actor SHALL have `runner: ollama`, `runtime: ollama`, a `model` that is a small tool-capable model
named in one place in core, no options, `effects` with `write: ["**"]`, an empty `expect`, and the same short
character as the Claude Code audition. It SHALL leave `workspace` unset, and set no runtime of its own, so its runs
use the local Ollama and work in a worktree.

#### Scenario: The Ollama actor's file
- **WHEN** a person runs `troupe init --audition --runner ollama`
- **THEN** config's actor `lead` holds runner `ollama`, runtime `ollama`, the model, no options,
  `effects.write: ["**"]` and `expect: []`, and no `workspace`
- **AND** `.troupe/actors/lead.yaml` names the runner `ollama` and holds no options
- **AND** `.troupe/actors/lead.md` holds the character
- **AND** no file under `.troupe/runtimes/` is written

#### Scenario: What init prints for it
- **WHEN** a person runs `troupe init --audition --runner ollama`
- **THEN** the perform step's note says Ollama must be running, and names `ollama pull` with the actor's model

### Requirement: Config's kinds are actors and runtimes
Config SHALL have two kinds, `actors` and `runtimes` (spec: runtimes). Any other top-level key SHALL be refused,
naming the key and both kinds. A change SHALL be checked against every rule that spans the kinds, such as an actor
naming a runtime that exists.

#### Scenario: A kind that doesn't exist
- **WHEN** a person sets `services.openai.endpoint`
- **THEN** it is refused, naming `services` and the kinds `actors` and `runtimes`

#### Scenario: Removing a runtime an actor uses
- **WHEN** config defines `runtimes.myhost`, `actors.tester.runtime` is `myhost`, and a person unsets
  `runtimes.myhost`
- **THEN** it is refused, naming `actors.tester.runtime`, and nothing is recorded

#### Scenario: A merge that removes a runtime an actor uses
- **WHEN** one branch unsets `runtimes.myhost` and another sets `actors.tester.runtime=myhost`, and they are merged
- **THEN** the merged config is a conflict, naming `actors.tester.runtime`

### Requirement: The OpenAI audition can edit files on a small budget
The OpenAI example actor SHALL have `runner: openai`, `runtime: openai`, a `model` naming a small current OpenAI model
that calls tools over the Responses API, named in one place in core, options with `maxTurns` of 10 and
`maxTotalTokens` of 100000, `effects` with `write: ["**"]`, an empty `expect`, and the same short character as the
Claude Code audition. It SHALL leave `workspace` unset.

#### Scenario: The OpenAI actor's file
- **WHEN** a person runs `troupe init --audition --runner openai`
- **THEN** config's `actors.lead` holds runner `openai`, runtime `openai`, the model, options with `maxTurns` 10 and
  `maxTotalTokens` 100000, `effects.write: ["**"]` and `expect: []`, and no `workspace`
- **AND** `.troupe/actors/lead.yaml` names the runner (its runtime, model and effects reach the file with #288)
- **AND** `.troupe/actors/lead.md` holds the character

#### Scenario: What init prints for it
- **WHEN** a person runs `troupe init --audition --runner openai`
- **THEN** the perform step's note says the `openai` runtime's key must be set in `OPENAI_API_KEY`, and that a run
  costs money, within the actor's token budget

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

### Requirement: A change to an actor on a runner that isn't installed is refused
A change that leaves an actor on a runner that troupe knows but isn't installed, and sets or unsets anything under that
actor, SHALL be refused with `runner.not-installed`, recording nothing, since its options can't be checked. The error
SHALL name the actor's path, the runner and its extra. Removing the actor whole, or moving it to an installed runner,
SHALL NOT be refused for this.

#### Scenario: Defining an actor on an uninstalled runner
- **WHEN** a person runs `troupe config set actors.lead.runner=lm-studio` and the `lm-studio` runner, whose extra is
  `lm-studio`, isn't installed
- **THEN** it is refused with `runner.not-installed`, naming `actors.lead.runner`, `lm-studio` and
  `troupe-run[lm-studio]`
- **AND** nothing is recorded

#### Scenario: Changing an existing actor's character
- **WHEN** `lead` is on the `lm-studio` runner, which isn't installed, and a person sets `actors.lead.character`
- **THEN** it is refused with `runner.not-installed`, and nothing is recorded

#### Scenario: Removing the actor
- **WHEN** `lead` is on the `lm-studio` runner, which isn't installed, and a person runs `troupe config unset
  actors.lead`
- **THEN** the change is recorded

#### Scenario: Moving the actor to an installed runner
- **WHEN** `lead` is on the `lm-studio` runner, which isn't installed, and a person sets `actors.lead.runner=scripted`
  and unsets `actors.lead.options`
- **THEN** the change is checked against the scripted runner's options schema, and recorded when it passes

### Requirement: Another actor's uninstalled runner doesn't block config
When config is checked whole, for a change to something else or a merge, an actor whose runner troupe knows but isn't
installed SHALL be checked against the actor schema and the effects rules, and its options SHALL be left unchecked
rather than refused. Its options are checked when it is next changed or performed where its runner is installed.

#### Scenario: Changing another actor
- **WHEN** `lead` is on the `lm-studio` runner, which isn't installed, and a person sets `actors.tester.runner=scripted`
- **THEN** the change is recorded

#### Scenario: A merge on a machine without the runner
- **WHEN** two branches' config streams are merged where `lead`'s `lm-studio` runner isn't installed, and one branch
  changed `lead`'s options
- **THEN** the merge isn't in conflict for `lead`'s options, and performing `lead` there is refused with
  `runner.not-installed`

#### Scenario: The actor's effects are still checked
- **WHEN** `lead` is on the `lm-studio` runner, which isn't installed, one branch expects `docs/a.md` while `lead` may
  write `docs/**`, and another narrows its writes to `out/**`, and they are merged
- **THEN** the merge is in conflict, naming `lead` and that `docs/a.md` is expected but no effect covers it

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
