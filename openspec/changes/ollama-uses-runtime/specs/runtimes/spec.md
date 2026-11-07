## ADDED Requirements

### Requirement: Options a runner moved to its runtime are refused with the move
An `ollama` actor whose options hold `model` or `endpoint` SHALL be refused wherever config is checked, naming the
option and saying it moved to the actor's runtime. The fix SHALL be one `troupe config set` that, run as given, sets
the actor's runtime and model and its options to the rest, leaves config valid, and changes no existing runtime.

#### Scenario: The model the audition used to write
- **WHEN** config holds an actor `lead` on `ollama` with `options.model` `qwen3:4b`, no runtime and no other option,
  and a person performs it
- **THEN** perform fails with `config.invalid`, naming `actors.lead.options.model` and saying it moved to the
  runtime, and its fix is `troupe config set actors.lead.runtime=ollama actors.lead.model=qwen3:4b
  'actors.lead.options={}'`, and nothing is recorded

#### Scenario: The fix run as given
- **WHEN** a person runs the fix that refusal gives
- **THEN** the change is recorded, `lead` names the runtime `ollama` with the model `qwen3:4b` and no options, and
  config breaks no rule

#### Scenario: Other options are kept
- **WHEN** the actor's options are `{"model": "qwen3:4b", "maxTurns": 20}`
- **THEN** the fix sets `'actors.lead.options={"maxTurns":20}'`, keeping `maxTurns`

#### Scenario: An endpoint on another host
- **WHEN** the actor `lead`'s options hold `endpoint` `http://gpu-box.local:11434`, and no runtime has that endpoint
- **THEN** the fix sets `actors.lead.runtime=lead` and `runtimes.lead.endpoint=http://gpu-box.local:11434`, and sets
  nothing under `runtimes.ollama`, so other actors on `ollama` keep their endpoint

#### Scenario: An endpoint a runtime already has
- **WHEN** the actor's options hold `endpoint` `http://gpu-box.local:11434`, and config's runtime `gpu` has that
  endpoint
- **THEN** the fix sets the actor's runtime to `gpu`, and defines no runtime

#### Scenario: Two actors on different hosts
- **WHEN** two old actors hold different `options.endpoint`s, and a person runs the first one's fix, then the second's
- **THEN** each actor's runs go to the endpoint it held, and so do the runs of every actor that was already on
  `ollama`

#### Scenario: The default endpoint
- **WHEN** the actor's options hold `endpoint` `http://127.0.0.1:11434`, the built-in runtime's, and config doesn't
  change `runtimes.ollama.endpoint`
- **THEN** the fix sets the runtime `ollama` and defines no runtime

#### Scenario: An unrelated change
- **WHEN** config holds such an actor and a person sets a value on another actor
- **THEN** it is refused with the same rule and fix, since the change would leave config breaking it

## MODIFIED Requirements

### Requirement: An actor names its runtime and may set its model
An actor MAY name a `runtime`, which SHALL be a built-in runtime or one in config, and MAY set a `model`. An actor
SHALL name a runtime when its runner requires one, SHALL NOT name one when its runner takes none, and SHALL NOT set a
`model` without a runtime.

#### Scenario: A runtime that doesn't exist
- **WHEN** a person sets `actors.tester.runtime=nowhere`
- **THEN** it is refused, naming the path and the runtimes that exist

#### Scenario: A runner that takes no runtime
- **WHEN** an actor whose runner is `claude-code` names the runtime `openai`
- **THEN** it is refused, naming the path and saying the `claude-code` runner takes no runtime

#### Scenario: A model without a runtime
- **WHEN** a person sets `actors.tester.model=gpt-test` and `tester` names no runtime
- **THEN** it is refused, naming `actors.tester.runtime`

#### Scenario: An Ollama actor without a runtime
- **WHEN** a person sets `actors.tester.runner=ollama` and `tester` names no runtime
- **THEN** it is refused, naming `actors.tester.runtime` and saying the `ollama` runner needs one, listing the
  runtimes there are
