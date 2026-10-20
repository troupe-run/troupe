# Design

## Context

See proposal.md for why. The agreed text is declared in troupe-run/infrastructure's `tofu/descriptions.json`:

- tagline: "Your agents need a director."
- sentence: "troupe runs your development process with a team of agents, asking only when it needs you."
- status: "Pre-alpha: there's nothing to install yet."

The org profile (`org-profile/profile/README.md` there) is the nearest model for the README: the tagline in bold, a
paragraph that opens with the sentence and goes on with "Work branches and loops, decisions go to whoever owns them,
and every decision records who made it.", then the status line. Nothing in this repository reads the declaration,
and no test or spec pins any of the seven places' wording (`troupe --help` included).

## Goals / Non-Goals

**Goals:**
- Every place in this repository that introduces troupe in one line says it the agreed way.

**Non-Goals:**
- A test or generator that keeps the places in step. That's single-sourcing, which belongs with #120; a test that
  compares hand-copied strings with each other would be one more copy to keep in step.

## Decisions

### D1: The exact text in each place

Each place keeps its own grammatical form (a sentence that starts "troupe runs", or a summary that starts "Run"), and
only the words after "process" change. The declared sentence is used word for word wherever a full sentence about
troupe appears.

| Place | Today | After |
|---|---|---|
| `README.md`, paragraph under the tagline | "troupe runs your development process with agents and people in named roles. Work branches…" | "troupe runs your development process with a team of agents, asking only when it needs you. Work branches and loops, decisions go to whoever owns them, and every decision records who made it." |
| `README.md`, status paragraph | "**Status: pre-alpha.** There's nothing to install yet. What exists so far…" | "Pre-alpha: there's nothing to install yet. What exists so far…" (the rest unchanged) |
| `docs/programme/what-is-troupe.md`, front-matter `description` and opening line | "troupe runs your development process with agents and people in named roles." | "troupe runs your development process with a team of agents, asking only when it needs you." |
| `packages/troupe/pyproject.toml`, `description` | "Run your development process with agents and people in named roles." | "Run your development process with a team of agents, asking only when it needs you." |
| `packages/troupe/src/troupe/cli/parser.py`, root parser `description` | same as `pyproject.toml` | same as `pyproject.toml` |
| `packages/troupe/src/troupe/__init__.py`, docstring | "troupe: run your development process with agents and people in named roles." | "troupe: run your development process with a team of agents, asking only when it needs you." |
| `CLAUDE.md`, opening sentence | "troupe runs a development process with agents and people in named roles." | "troupe runs your development process with a team of agents, asking only when it needs you." |
| `openspec/config.yaml`, opening sentence of `context` | "troupe runs a software process with agents and people in named roles." | "troupe runs a software process with a team of agents, asking only when it needs you." |

Two variants, and why:

- **The package summary and `--help`** keep their imperative "Run …", because a package summary and a command's help
  describe what the thing does, and both read that way today.
- **`openspec/config.yaml`** keeps "a software process" rather than "your", because it's written to the agents
  planning changes, not to a reader who owns the process. Its later constraint, "Humans hold roles like agents.",
  still says what "named roles" used to, so nothing an agent relies on is lost. `CLAUDE.md` takes the sentence word
  for word: it's read by people as well as agents, and "a development process" there was only a variant.

The README's status line drops the bold "**Status:**" label, as in the org profile, so the line reads the same in both.

Alternative considered: change only the README, as #130 lists, and open a follow-up for the rest. The owner chose to
bring all seven into step here.

### D2: How the change is checked

There's no behaviour to test, so the check is a search: after the edits, `git grep -n "named roles"` finds nothing
outside `openspec/changes/` (archived changes record history and stay as written). `uv run scripts/check.py` passes,
and `uv run troupe --help` shows the new description.

## Risks / Trade-offs

- [The places drift again the next time the sentence changes] → #120 owns single-sourcing. Until then, the search in
  D2 is how to find every copy.
- [The docs page changes on troupe.run only after a release] → expected: the site publishes released docs, and the
  release already tells troupe.run that `docs/` may have changed.
