# Spec Delta

## ADDED Requirements

### Requirement: A script can check the character it received
A script SHALL be able to hold a step that checks the character in `run/start` against a `sha256:` hash, or checks
that there is none. When the check fails, the runner SHALL end the run with an error result naming the hash it
expected and the hash it received, and play no later step.

#### Scenario: The character matches
- **WHEN** a script checks for the hash of "You are the tester." and `run/start` carries that character
- **THEN** the runner plays the script's next step

#### Scenario: The character differs
- **WHEN** a script checks for one hash and `run/start` carries a different character, or none
- **THEN** the run ends with an error result naming both hashes, and no later step is played

### Requirement: The scripted runner's schemas are installed with it
The scripted runner's published schemas SHALL be installed with the plugin, so troupe can find its options schema
from the installed plugin, without starting the runner.

#### Scenario: The options schema from an installed plugin
- **WHEN** troupe checks an actor's options for the scripted runner
- **THEN** it reads the options schema from the installed plugin, and the runner isn't started
