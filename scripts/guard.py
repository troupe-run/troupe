"""Workflow guardrails for this repository (spec: development-workflow).

Every rule is a pure function from facts to a Decision. Thin entry points gather the facts, apply
the rules, honour a person-granted override, and refuse or allow:

    guard.py pre-commit              git hook (.githooks/pre-commit)
    guard.py commit-msg FILE         git hook (.githooks/commit-msg)
    guard.py claude-pre-tool-use     Claude Code PreToolUse hook (.claude/settings.json)
    guard.py claude-session-start    Claude Code SessionStart hook
    guard.py override RULE --reason  a person grants one override, from their own terminal

Standard library only, so it runs under `uv run --no-project` without installing anything.
These guardrails stop honest shortcuts; they are not a security boundary (design D1).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

# Rule ids, as named in refusals, overrides and docs/development-workflow.md (design D7).
OVERRIDABLE_RULES = (
    "commit-on-main",
    "commit-branch-change",
    "commit-message",
    "commit-checks",
    "archive-incomplete",
    "edit-branch-change",
    "pr-closes-issue",
    "skip-hooks",
    "command-unparseable",
)
TAMPER_RULE = "guard-tamper"
"""Refuses an agent's attempt to grant itself an override. Never overridable."""
RULES = (*OVERRIDABLE_RULES, TAMPER_RULE)

HOOKS_PATH = ".githooks"
GUARD_DIR = "troupe-guard"
COMMIT_TYPES = (
    "feat", "fix", "docs", "build", "ci", "test", "refactor", "perf", "style", "chore", "revert",
)  # fmt: skip
COMMIT_PATTERN = re.compile(rf"^({'|'.join(COMMIT_TYPES)})(\([a-z0-9][a-z0-9-]*\))?!?: \S")
AUTOSQUASH_PREFIXES = ("fixup! ", "squash! ", "amend! ")
CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?\s+"
    r"(?:#\d+|[\w.-]+/[\w.-]+#\d+|https://github\.com/[\w.-]+/[\w.-]+/issues/\d+)",
    re.IGNORECASE,
)
UNTICKED = re.compile(r"^\s*- \[(?![xX]\])[^\]]*\]\s*(.*)$", re.MULTILINE)
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
SHELL_TOOLS = ("Bash", "PowerShell")


@dataclass(frozen=True)
class Decision:
    """Allow (rule is None), or refuse with the rule id, the problem and the fix."""

    rule: str | None = None
    problem: str = ""
    fix: str = ""

    @property
    def refused(self) -> bool:
        return self.rule is not None

    def text(self) -> str:
        return f"guard: {self.rule}: {self.problem}\n  fix: {self.fix}"


ALLOW = Decision()


# --- facts ---------------------------------------------------------------------------------


REPOSITORY_LOCATION_VARIABLES = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_PREFIX",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE",
    }
)
"""Set by git while a hook runs. They pin git to that repository, so nested git calls (such as
the tests' temporary repositories) must not inherit them. Other GIT_* settings are the user's."""


def _git_env() -> dict[str, str]:
    """The environment without the hook-time repository-location variables."""
    return {k: v for k, v in os.environ.items() if k not in REPOSITORY_LOCATION_VARIABLES}


def git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False, env=_git_env()
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def repo_root(start: Path) -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        capture_output=True,
        text=True,
        check=False,
        env=_git_env(),
    )
    return Path(result.stdout.strip()) if result.returncode == 0 else None


def current_branch(root: Path) -> str | None:
    """The checked-out branch, read from the rebase state while a rebase has HEAD detached."""
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False)
    if branch and branch != "HEAD":
        return branch
    git_dir = Path(git(root, "rev-parse", "--absolute-git-dir"))
    for state in ("rebase-merge", "rebase-apply"):
        head_name = git_dir / state / "head-name"
        if head_name.is_file():
            return head_name.read_text(encoding="utf-8").strip().removeprefix("refs/heads/")
    return None


def matching_change(root: Path, branch: str | None) -> Path | None:
    """The OpenSpec change named like ``branch``: active, or archived on that branch (design D3)."""
    if not branch or branch == "main" or branch == "archive":
        return None
    changes = root / "openspec" / "changes"
    active = changes / branch
    if active.is_dir():
        return active
    archived = re.compile(rf"^\d{{4}}-\d{{2}}-\d{{2}}-{re.escape(branch)}$")
    archive = changes / "archive"
    if archive.is_dir():
        for candidate in sorted(archive.iterdir()):
            if candidate.is_dir() and archived.match(candidate.name):
                return candidate
    return None


# --- git-level rules -------------------------------------------------------------------------


def commit_on_main(branch: str | None) -> Decision:
    if branch == "main":
        return Decision(
            "commit-on-main",
            "commits aren't made on main; work reaches main through a pull request.",
            "Create a branch named after the OpenSpec change: git switch -c <change-name>",
        )
    return ALLOW


def commit_branch_change(root: Path, branch: str | None) -> Decision:
    if branch is None:
        return Decision(
            "commit-branch-change",
            "HEAD is detached, so this commit belongs to no change.",
            "Switch to the change's branch: git switch <change-name>",
        )
    if branch != "main" and matching_change(root, branch) is None:
        return Decision(
            "commit-branch-change",
            f"branch '{branch}' has no matching OpenSpec change "
            f"(openspec/changes/{branch}/, active or archived).",
            f"Propose the change (/opsx:propose {branch}), or switch to the branch of the change "
            "this work belongs to.",
        )
    return ALLOW


def commit_message(message: str) -> Decision:
    lines = [line for line in message.splitlines() if not line.startswith("#")]
    first = next((line for line in lines if line.strip()), "")
    if first.startswith(AUTOSQUASH_PREFIXES) or COMMIT_PATTERN.match(first):
        return ALLOW
    example = "feat(cli): add --version"
    if first.startswith('Revert "'):
        fix = "Write it as a Conventional Commit: revert: <what is reverted> (git revert --edit)."
    elif first.startswith("Merge "):
        fix = "History stays linear: rebase onto the target instead of merging (git rebase main)."
    else:
        fix = (
            f"Start the first line with a type, an optional (scope) and ': ', e.g. '{example}'. "
            f"Types: {', '.join(COMMIT_TYPES)}."
        )
    return Decision("commit-message", f"'{first}' isn't a Conventional Commit.", fix)


def unticked_archived_tasks(staged: Iterable[str], read_staged: ReadStaged) -> Decision:
    """Refuse when a staged archived change still has an unticked task (design D7)."""
    archived = re.compile(r"^openspec/changes/archive/([^/]+)/")
    seen: set[str] = set()
    for path in staged:
        match = archived.match(path)
        if match is None or match.group(1) in seen:
            continue
        name = match.group(1)
        seen.add(name)
        tasks = read_staged(f"openspec/changes/archive/{name}/tasks.md")
        if tasks is None:
            continue
        unticked = UNTICKED.search(tasks)
        if unticked is not None:
            return Decision(
                "archive-incomplete",
                f"archived change '{name}' has an unticked task: {unticked.group(1).strip()[:120]}",
                "Finish and tick every task before archiving, or move the change back out of "
                "openspec/changes/archive/.",
            )
    return ALLOW


class ReadStaged:
    """Reads a file's staged contents (None when it isn't staged or doesn't exist)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def __call__(self, path: str) -> str | None:
        result = subprocess.run(
            ["git", "show", f":{path}"],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
            env=_git_env(),
        )
        return result.stdout if result.returncode == 0 else None


def commit_checks(root: Path) -> Decision:
    """Refuse unless the tracked work equals what's staged and scripts/check.py passes (D4)."""
    unstaged = git(root, "diff", "--name-only")
    if unstaged:
        files = ", ".join(unstaged.splitlines()[:5])
        return Decision(
            "commit-checks",
            f"tracked files have unstaged changes ({files}), so the check wouldn't test what's "
            "being committed.",
            "Stage them (git add) or set them aside (git stash --keep-index), then commit again.",
        )
    check = root / "scripts" / "check.py"
    result = subprocess.run(
        ["uv", "run", "--quiet", str(check)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=_git_env(),
    )
    if result.returncode != 0:
        output = result.stdout + result.stderr
        failed = re.search(r"^check: (.+?) failed", output, re.MULTILINE)
        gate = failed.group(1) if failed else "a"
        return Decision(
            "commit-checks",
            f"the {gate} gate failed.",
            "Run `uv run scripts/check.py`, fix what it reports, then commit again.",
        )
    return ALLOW


# --- Claude Code rules -----------------------------------------------------------------------

HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][\w-]*)\1")
OPERATORS = ("&&", "||", ";", "|", "&", "\n")


def strip_heredocs(command: str) -> str:
    """Drop heredoc bodies: they are data (often commit messages), not shell words."""
    out: list[str] = []
    lines = command.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        delimiters = [m.group(2) for m in HEREDOC.finditer(line)]
        i += 1
        for delimiter in delimiters:
            while i < len(lines) and lines[i].strip() != delimiter:
                i += 1
            i += 1  # the delimiter line itself
    return "\n".join(out)


def split_command(command: str) -> list[list[str]]:
    """Split a shell command into its simple commands, each as a list of words.

    Raises ValueError when the text can't be parsed (for example, unbalanced quotes).
    """
    text = strip_heredocs(command)
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(text):
        char = text[i]
        if quote:
            current.append(char)
            if char == "\\" and quote == '"' and i + 1 < len(text):
                current.append(text[i + 1])
                i += 1
            elif char == quote:
                quote = None
        elif char in "'\"":
            quote = char
            current.append(char)
        elif char == "\\" and i + 1 < len(text):
            current.append(text[i : i + 2])
            i += 1
        else:
            operator = next((op for op in OPERATORS if text.startswith(op, i)), None)
            if operator is None:
                current.append(char)
            else:
                segments.append("".join(current))
                current = []
                i += len(operator) - 1
        i += 1
    if quote:
        raise ValueError("unbalanced quotes")
    segments.append("".join(current))
    return [words for segment in segments if (words := shlex.split(segment, posix=True))]


def _program(words: Sequence[str]) -> tuple[str, list[str]]:
    """The program name and its arguments, after any leading VAR=value assignments."""
    index = 0
    while index < len(words) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[index]):
        index += 1
    if index >= len(words):
        return "", []
    name = Path(words[index]).name.lower().removesuffix(".exe")
    return name, list(words[index + 1 :])


def _git_subcommand(args: list[str]) -> tuple[list[str], str | None, list[str]]:
    """Split git's arguments into its global options, the subcommand and the rest."""
    globals_: list[str] = []
    index = 0
    while index < len(args) and args[index].startswith("-"):
        globals_.append(args[index])
        if args[index] in ("-c", "-C", "--git-dir", "--work-tree") and index + 1 < len(args):
            globals_.append(args[index + 1])
            index += 1
        index += 1
    if index >= len(args):
        return globals_, None, []
    return globals_, args[index], args[index + 1 :]


def _sets_hooks_path_elsewhere(setting: str) -> bool:
    key, _, value = setting.partition("=")
    return key.strip().lower() == "core.hookspath" and value.strip() != HOOKS_PATH


def skip_hooks(words: Sequence[str]) -> Decision:
    program, args = _program(words)
    if program != "git":
        return ALLOW
    globals_, sub, rest = _git_subcommand(args)
    refused = Decision(
        "skip-hooks",
        "this would skip or disable the repository's git hooks.",
        "Fix what the hook reports instead. If a skip is really needed, ask the owner to grant "
        "an override.",
    )
    for index, option in enumerate(globals_):
        setting = globals_[index + 1] if index + 1 < len(globals_) else ""
        if option == "-c" and _sets_hooks_path_elsewhere(setting):
            return refused
    if "--no-verify" in rest:
        return refused
    if sub == "commit":
        value_flags = set("mFCct")
        skip_next = False
        for word in rest:
            if skip_next:
                skip_next = False
                continue
            if word == "--":
                break
            if word.startswith("-") and not word.startswith("--"):
                for position, flag in enumerate(word[1:]):
                    if flag == "n":
                        return refused
                    if flag in value_flags:
                        skip_next = position == len(word) - 2
                        break
            elif word in (
                "--message",
                "--file",
                "--reuse-message",
                "--reedit-message",
                "--template",
            ):
                skip_next = True
    if sub == "config":
        lowered = [word.lower() for word in rest]
        if "core.hookspath" in lowered:
            position = lowered.index("core.hookspath")
            value = rest[position + 1] if position + 1 < len(rest) else None
            removing = any(word in ("--unset", "--unset-all", "--remove-section") for word in rest)
            reading = value is None and not removing
            if removing or (not reading and value != HOOKS_PATH):
                return refused
    return ALLOW


def pr_closes_issue(words: Sequence[str], cwd: Path) -> Decision:
    program, args = _program(words)
    if program != "gh" or args[:2] != ["pr", "create"]:
        return ALLOW
    rest = args[2:]
    body: str | None = None
    for index, word in enumerate(rest):
        name, _, inline = word.partition("=")
        if name in ("-f", "--fill", "--fill-first", "--fill-verbose"):
            body = None
            break
        if name in ("-b", "--body"):
            body = inline if inline else (rest[index + 1] if index + 1 < len(rest) else "")
        elif name in ("-F", "--body-file"):
            path = inline if inline else (rest[index + 1] if index + 1 < len(rest) else "-")
            if path == "-":
                body = None
                break
            file = Path(path) if Path(path).is_absolute() else cwd / path
            body = file.read_text(encoding="utf-8") if file.is_file() else ""
    if body is not None and CLOSING.search(body):
        return ALLOW
    return Decision(
        "pr-closes-issue",
        "the pull request's description must close the issue it delivers, and it can't be "
        "read from --fill or stdin.",
        "Pass the description with --body or --body-file, including a line like 'Closes #22'.",
    )


TAMPER = Decision(
    TAMPER_RULE,
    "agents can't grant themselves an override or touch the override files.",
    "Ask the owner. Only a person, in their own terminal, can grant an override.",
)


def guard_tamper(words: Sequence[str]) -> Decision:
    """Refuse a command that runs the override, or names a path in the override directory.

    Works on parsed words, so a commit message that merely mentions the override command (one
    quoted word containing spaces) isn't mistaken for running it.
    """
    for index, word in enumerate(words):
        runs_override = word.lower().endswith("guard.py") and words[index + 1 : index + 2] == [
            "override"
        ]
        names_override_path = GUARD_DIR in word.lower() and not re.search(r"\s", word)
        if runs_override or names_override_path:
            return TAMPER
    return ALLOW


def shell_decisions(command: str, cwd: Path) -> list[Decision]:
    text = strip_heredocs(command)
    try:
        simple_commands = split_command(command)
    except ValueError as error:
        if GUARD_DIR in text.lower() or re.search(r"guard\.py\S*\s+override\b", text.lower()):
            return [TAMPER]
        if not re.search(r"\b(git|gh)\b", text):
            return [ALLOW]
        return [
            Decision(
                "command-unparseable",
                f"this git or gh command couldn't be parsed ({error}), so the guardrails can't "
                "check it.",
                "Simplify the command: one git or gh step at a time, with balanced quotes.",
            )
        ]
    decisions: list[Decision] = []
    for words in simple_commands:
        tamper = guard_tamper(words)
        if tamper.refused:
            return [tamper]
        decisions.append(skip_hooks(words))
        decisions.append(pr_closes_issue(words, cwd))
    return decisions or [ALLOW]


def edit_decision(root: Path, file_path: str, branch: str | None) -> Decision:
    target = Path(file_path)
    target = target if target.is_absolute() else root / target
    resolved = target.resolve()
    real_root = root.resolve()
    if not resolved.is_relative_to(real_root):
        return ALLOW
    if ".git" in resolved.relative_to(real_root).parts:
        return Decision(
            TAMPER_RULE,
            "files under .git/ aren't edited directly; it holds the override files.",
            "Use git commands for repository state. Ask the owner for an override.",
        )
    if matching_change(root, branch) is None:
        where = "main" if branch == "main" else f"branch '{branch}'"
        return Decision(
            "edit-branch-change",
            f"edits need an OpenSpec change matching the branch, and {where} has none.",
            "Create or switch to the branch named after the change (git switch -c <change-name> "
            "after /opsx:propose <change-name>).",
        )
    return ALLOW


# --- overrides -------------------------------------------------------------------------------


def _guard_dir(root: Path) -> Path:
    common = Path(git(root, "rev-parse", "--git-common-dir"))
    return (common if common.is_absolute() else root / common) / GUARD_DIR


def grant_override(root: Path, rule: str, reason: str) -> Path:
    if rule not in OVERRIDABLE_RULES:
        known = ", ".join(OVERRIDABLE_RULES)
        raise SystemExit(f"guard: '{rule}' isn't an overridable rule. Rules: {known}")
    if not reason.strip():
        raise SystemExit("guard: an override needs a reason.")
    granted_by = git(root, "config", "user.email", check=False)
    if not granted_by:
        raise SystemExit(
            "guard: no git user.email is set, so the override can't say who granted it."
        )
    directory = _guard_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "rule": rule,
        "reason": reason.strip(),
        "granted_by": granted_by,
        "granted_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    path = directory / "override.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def consume_override(root: Path, decision: Decision, action: str) -> bool:
    """Use a pending override for this refusal, if there is one. Returns True when allowed."""
    if decision.rule not in OVERRIDABLE_RULES:
        return False
    directory = _guard_dir(root)
    pending = directory / "override.json"
    if not pending.is_file():
        return False
    record = json.loads(pending.read_text(encoding="utf-8"))
    if record.get("rule") != decision.rule:
        return False
    pending.unlink()
    record["used_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    record["allowed"] = action
    with (directory / "overrides.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(record) + "\n")
    return True


def first_refusal(root: Path, decisions: Iterable[Decision], action: str) -> Decision | None:
    for decision in decisions:
        if decision.refused and not consume_override(root, decision, action):
            return decision
    return None


# --- entry points ----------------------------------------------------------------------------


def run_pre_commit(root: Path) -> int:
    branch = current_branch(root)
    staged = git(root, "diff", "--cached", "--name-only").splitlines()

    def checks() -> Iterable[Decision]:
        yield commit_on_main(branch)
        yield commit_branch_change(root, branch)
        yield unticked_archived_tasks(staged, ReadStaged(root))
        yield commit_checks(root)

    refusal = first_refusal(root, checks(), f"commit on {branch}")
    if refusal is not None:
        print(refusal.text(), file=sys.stderr)
        return 1
    return 0


def run_commit_msg(root: Path, message_file: Path) -> int:
    message = message_file.read_text(encoding="utf-8")
    first = next((line for line in message.splitlines() if line.strip()), "")
    refusal = first_refusal(root, [commit_message(message)], f"commit message: {first}")
    if refusal is not None:
        print(refusal.text(), file=sys.stderr)
        return 1
    return 0


def run_claude_pre_tool_use(payload: dict[str, object], stdout: TextIO | None = None) -> int:
    out = sys.stdout if stdout is None else stdout
    tool = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    cwd = Path(str(payload.get("cwd") or os.getcwd()))
    root = repo_root(cwd) if cwd.is_dir() else None
    if root is None:
        return 0
    decisions: list[Decision]
    action: str
    if tool in EDIT_TOOLS:
        file_path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        if not file_path:
            return 0
        decisions = [edit_decision(root, file_path, current_branch(root))]
        action = f"{tool} {file_path}"
    elif tool in SHELL_TOOLS:
        command = str(tool_input.get("command", ""))
        decisions = shell_decisions(command, cwd)
        action = f"{tool}: {command[:200]}"
    else:
        return 0
    refusal = first_refusal(root, decisions, action)
    if refusal is not None:
        deny = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": refusal.text(),
            }
        }
        print(json.dumps(deny), file=out)
    return 0


WORKFLOW_SUMMARY = (
    "This repository's workflow is enforced by guardrails (docs/development-workflow.md): "
    "issue -> OpenSpec change (/opsx:propose) on a branch named after the change -> "
    "/opsx:apply -> PR that closes the issue -> archive on the branch -> merge -> comment on and "
    "close the issue. Conventional Commits; scripts/check.py passes before every commit. "
    "When a guardrail refuses, follow its fix; don't work around it. Only the owner can grant "
    "an override."
)


def run_claude_session_start(root: Path, stdout: TextIO | None = None) -> int:
    out = sys.stdout if stdout is None else stdout
    notes: list[str] = []
    configured = git(root, "config", "--get", "core.hooksPath", check=False)
    if configured != HOOKS_PATH:
        git(root, "config", "core.hooksPath", HOOKS_PATH)
        notes.append(
            f"Activated the repository's git hooks (core.hooksPath was "
            f"{configured or 'unset'}; now {HOOKS_PATH})."
        )
    branch = current_branch(root)
    change = matching_change(root, branch)
    if change is not None:
        notes.append(
            f"Branch '{branch}' matches the OpenSpec change "
            f"{change.relative_to(root).as_posix()}: edits and commits are allowed."
        )
    else:
        notes.append(
            f"Branch '{branch}' has no matching OpenSpec change: edits and commits will be "
            "refused until you switch to, or create, the change's branch."
        )
    context = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": " ".join([WORKFLOW_SUMMARY, *notes]),
        }
    }
    print(json.dumps(context), file=out)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="guard.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="entry", required=True, metavar="ENTRY")
    sub.add_parser("pre-commit", help="git pre-commit hook")
    message = sub.add_parser("commit-msg", help="git commit-msg hook")
    message.add_argument("message_file")
    sub.add_parser("claude-pre-tool-use", help="Claude Code PreToolUse hook (JSON on stdin)")
    sub.add_parser("claude-session-start", help="Claude Code SessionStart hook")
    grant = sub.add_parser("override", help="grant one override (a person, in a terminal)")
    grant.add_argument("rule", choices=OVERRIDABLE_RULES)
    grant.add_argument("--reason", required=True)
    args = parser.parse_args(argv)

    if args.entry == "claude-pre-tool-use":
        return run_claude_pre_tool_use(json.loads(sys.stdin.read() or "{}"))
    start = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    root = repo_root(start)
    if root is None:
        print("guard: not inside a git repository.", file=sys.stderr)
        return 1
    if args.entry == "pre-commit":
        return run_pre_commit(root)
    if args.entry == "commit-msg":
        return run_commit_msg(root, Path(args.message_file))
    if args.entry == "claude-session-start":
        sys.stdin.read()
        return run_claude_session_start(root)
    path = grant_override(root, args.rule, args.reason)
    print(f"guard: override granted for '{args.rule}' (one action). Recorded in {path.parent}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
