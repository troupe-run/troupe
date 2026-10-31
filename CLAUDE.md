# troupe

troupe runs your development process with a team of agents, asking only when it needs you. This repository is the
app: see [README.md](README.md) for the layout and [openspec/config.yaml](openspec/config.yaml) for the constraints
every change respects.

## How work happens here

Every change, however small, follows one path. The full guide is the org's
[CONTRIBUTING.md](https://github.com/troupe-run/.github/blob/main/CONTRIBUTING.md).

1. **An issue** (Feature, Bug or Decision) says what and why.
2. **An OpenSpec change** says how: `/opsx:propose <name>`, on a branch named exactly `<name>`. Its proposal cites
   the issue. Design decisions are surfaced in the proposal or design before code depends on them.
3. **`/opsx:apply`** builds it. A task is ticked only when its verification has run and passed.
4. **A draft pull request** closes the issue (`Closes #n`): `gh pr create --draft`. Claude reviews it; CI's legs
   wait until it's marked ready.
5. **Claude's review is acted on**, after the review of the last push: fix or answer each finding, resolve only nits,
   and raise decisions and disputed must-fixes with the owner. The review resolves its own must-fixes once they're
   addressed, judging a reply to one when it's posted; if that run fails, re-run it (`gh run rerun <id>`). Once the
   review of the last push leaves no must-fix or decision open, **mark it ready** (`gh pr ready <n>`): CI runs on
   Linux, macOS and Windows, and every job must pass. Marking ready starts no review. A merge needs every
   conversation resolved ([development-workflow.md, "Claude's review"](https://github.com/troupe-run/infrastructure/blob/main/docs/development-workflow.md#claudes-review)).
6. **`/opsx:archive`** runs on the branch before merging, so the PR lands code, tests and specs together. The pull
   request then goes into the merge queue, which merges it by rebase once `check`, `guard (workflow rules)` and `DCO`
   pass on the commit it tested: `gh pr merge <n>`, or "Merge when ready", queues it. `gh pr merge <n> --rebase
   --admin` skips the queue, and is only for emergencies, such as clearing a stuck queue.
7. **After the merge**, comment on the issue with the PR and the archived change.

Commits are Conventional Commits (`feat(cli): ...`), signed, and `uv run scripts/check.py` passes before each one.

## Guardrails

Git hooks and Claude Code hooks enforce the path above. They're maintained in `troupe-run/infrastructure`, and
[development-workflow.md](https://github.com/troupe-run/infrastructure/blob/main/docs/development-workflow.md) lists every rule. When one refuses
an action:

- **Follow its fix.** Don't look for another route to the same action. The hooks aren't a security boundary, so
  getting round one is possible, and it's exactly the shortcut they exist to stop.
- **If the rule seems wrong for the situation, stop and ask the owner.** Only a person, in their own terminal, can
  grant an override, and every use is logged.
