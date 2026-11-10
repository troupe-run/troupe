## MODIFIED Requirements

### Requirement: A missing plugin's refusal fits any install
When a plugin troupe needs isn't installed, or ships no schemas, troupe SHALL refuse, naming the plugin's package: a
runner in troupe's table with `runner.not-installed`, naming its extra when it has one (spec: runs), and any other
plugin with `schemas.plugin-missing`. The fix SHALL suit any install: the runner's extra or a reinstall with the install
page's command, or `uv sync` in a checkout. It SHALL NOT say that an install brings every runner.

#### Scenario: A runner that isn't installed
- **WHEN** troupe needs the schemas of a runner in its table whose package isn't installed
- **THEN** it refuses with `runner.not-installed`, naming the runner, the package and its extra, and the fix links to
  the install page for an installed troupe and names `uv sync` for a checkout

#### Scenario: A plugin that ships no schemas
- **WHEN** a runner's package is installed without a `schemas/` directory
- **THEN** troupe refuses with `schemas.plugin-missing`, naming the package, and the fix doesn't say that an install
  brings every runner

#### Scenario: The install page the fix links to
- **WHEN** the install page is moved or renamed in `docs/`
- **THEN** troupe's own tests fail, naming the address the fix links to
