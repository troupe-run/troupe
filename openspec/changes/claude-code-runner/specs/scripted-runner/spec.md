# Spec Delta

## REMOVED Requirements

### Requirement: Fixtures pair real engine output with protocol events
**Reason**: The fixtures are Claude Code's output, and the Claude Code runner's mapping is what they pin, so they
move to the Claude Code runner's plugin with their capture tool. The scripted runner still replays them; replaying a
recording is its own requirement ("Recorded streams replay verbatim").
**Migration**: The requirement continues as `claude-code-runner`'s "Fixtures pair real Claude Code output with
protocol events", which keeps its scenarios and adds the network, server and rate-limit retry fixtures. The fixtures
are at `plugins/runner-claude-code/fixtures/claude-code/`.

### Requirement: Fixtures hold no secrets
**Reason**: Moves with the fixtures to the Claude Code runner's plugin.
**Migration**: The requirement continues unchanged as `claude-code-runner`'s "Fixtures hold no secrets".
