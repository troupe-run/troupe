## MODIFIED Requirements

### Requirement: The campaign's selection is the OS-sensitive tests, named in one place
By default the campaign SHALL hunt the tests that depend on time, processes, signals or file watching, named as path
patterns in one place, and SHALL be able to hunt the whole suite instead. Each pattern SHALL match at least one test
file, checked by a test. A pattern naming test files SHALL match them under both `tests/unit/` and
`tests/integration/`, so moving a file between the two keeps it hunted.

#### Scenario: A new platform test file
- **WHEN** a new `packages/troupe/tests/integration/test_platform_*.py` or
  `packages/troupe/tests/unit/test_platform_*.py` file is added
- **THEN** the campaign hunts it without any change to the campaign
