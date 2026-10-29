## ADDED Requirements

### Requirement: A missing plugin's refusal fits any install
When a plugin troupe needs isn't installed, or ships no schemas, troupe SHALL refuse, naming the plugin's package. The
fix SHALL be right however troupe was installed: reinstall troupe with the command on the install page, which brings
every runner troupe knows, or, from a checkout of this repository, run `uv sync` there.

#### Scenario: A runner that isn't installed
- **WHEN** troupe needs the schemas of a runner whose package isn't installed
- **THEN** it refuses with `schemas.plugin-missing`, naming the package, and the fix links to the install page for
  an installed troupe and names `uv sync` for a checkout

#### Scenario: The install page the fix links to
- **WHEN** the install page is moved or renamed in `docs/`
- **THEN** troupe's own tests fail, naming the address the fix links to
