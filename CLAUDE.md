# troupe.run

troupe runs a development process with agents and people in named roles. This repository is the app: see
[README.md](README.md) for the layout and [openspec/config.yaml](openspec/config.yaml) for the constraints every
change respects.

## How work happens here

Every change, however small, follows one path. The full guide is the org's
[CONTRIBUTING.md](https://github.com/troupe-run/.github/blob/main/CONTRIBUTING.md).

1. **An issue** (Feature, Bug or Decision) says what and why.
2. **An OpenSpec change** says how: `/opsx:propose <name>`, on a branch named exactly `<name>`. Its proposal cites
   the issue. Design decisions are surfaced in the proposal or design before code depends on them.
3. **`/opsx:apply`** builds it. A task is ticked only when its verification has run and passed.
4. **A pull request** closes the issue (`Closes #n`). All CI jobs pass on Linux, macOS and Windows.
5. **`/opsx:archive`** runs on the branch before merging, so the PR lands code, tests and specs together.
6. **After the merge**, comment on the issue with the PR and the archived change.

Commits are Conventional Commits (`feat(cli): ...`), signed, and `uv run scripts/check.py` passes before each one.

## Guardrails

Git hooks and Claude Code hooks enforce the path above. [docs/development-workflow.md](docs/development-workflow.md)
lists every rule. When one refuses an action:

- **Follow its fix.** Don't look for another route to the same action. The hooks aren't a security boundary, so
  getting round one is possible, and it's exactly the shortcut they exist to stop.
- **If the rule seems wrong for the situation, stop and ask the owner.** Only a person, in their own terminal, can
  grant an override, and every use is logged.
