## ADDED Requirements

### Requirement: Every recorded version has its release tag
After each release run on `main`, the release workflow SHALL check that every version in the manifest, other than an
unreleased `0.0.0`, has its tag `<component>-v<version>`. When any is missing, the run SHALL fail, naming each missing
tag and pointing to the repair route in the release guide. It SHALL check even when release-please failed.

#### Scenario: A release run that made every tag
- **WHEN** a release run ends with a tag for every version in the manifest
- **THEN** the check passes

#### Scenario: A release run that skipped two components
- **WHEN** the manifest records `troupe-runner-ollama` at 0.1.0 and `protocol` at 0.2.0, and neither
  `troupe-runner-ollama-v0.1.0` nor `protocol-v0.2.0` exists
- **THEN** the run fails, and its output names both tags and the release guide's repair section

#### Scenario: A member that hasn't released
- **WHEN** a workspace member's version in the manifest is `0.0.0`
- **THEN** the check doesn't look for a tag for it

#### Scenario: A manifest entry with no component in the config
- **WHEN** the manifest has a path that `release-please-config.json` doesn't configure
- **THEN** the check fails, naming the path, rather than guessing its tag

#### Scenario: release-please failed
- **WHEN** release-please fails partway through a release run
- **THEN** the check still runs and names any tag it didn't make
