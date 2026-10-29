## MODIFIED Requirements

### Requirement: A plugin's published schemas are installed with it
Each plugin's published schemas SHALL be installed with the plugin, so troupe can read them without starting the
plugin, and without importing it. When a plugin troupe needs isn't installed, or ships no schemas, troupe SHALL refuse,
naming the plugin's package, with a fix that is right however troupe was installed: reinstalling troupe with the
install command on the install page, which brings every runner troupe knows, or, when troupe is run from a checkout of
this repository, `uv sync` in that checkout.

#### Scenario: A runner's options schema
- **WHEN** troupe checks an actor's options for the scripted runner
- **THEN** it reads the options schema the installed scripted runner publishes, and the runner isn't started

#### Scenario: A runner that isn't installed
- **WHEN** troupe needs the schemas of a runner whose package isn't installed
- **THEN** it refuses with `schemas.plugin-missing`, naming the package, and the fix links to the install page for
  an installed troupe and names `uv sync` for a checkout

#### Scenario: The install page the fix links to
- **WHEN** the install page is moved or renamed in `docs/`
- **THEN** troupe's own tests fail, naming the address the fix links to
