"""The actor's declared effects as Claude Code's permission rules (spec: claude-code-runner;
declared-effects design D8).

This is the runner's ``translated`` way of applying a declaration, through the plugin SDK's
``EffectsTranslation`` seam. It reads the SDK's normalised view, so every pattern is rooted at the
workspace in one form on every platform, and gives Claude Code:

- **a mode that denies whatever no rule allows:** ``dontAsk``, or ``plan`` when the options ask;
- **an allow rule for each write pattern,** ``Edit(//<workspace>/<pattern>)``, which covers every
  built-in tool that edits a file, and one for the scratch directory;
- **deny rules for the workspace's .git and .troupe,** which win over any allow;
- **the scratch directory** as a working directory, and as its temporary directory;
- **troupe's own Delete and Move,** as tools of the runner's MCP server, when the actor declares
  them: Claude Code has no tool for either, and shell rules match a command's text, not its paths.

Options that would let Claude Code change more than the declaration says are refused when they're
parsed (troupe_runner_claude_code.options); a pattern or path that Claude Code's rule syntax would
read differently from troupe's is refused here. What the rules
can't cover, an allowed shell rule or a loaded setting source, is said in a warning, and troupe's
audit checks the run's changes afterwards.
"""

from dataclasses import dataclass, field
from pathlib import Path, PurePath

from troupe_plugin_sdk.declaration import Declaration, Mode, posix_absolute
from troupe_runner_claude_code.options import MCP_SERVER, Options

SHELL_TOOLS = ("Bash", "PowerShell")
"""Claude Code's shells, which can change any file whatever the rules say."""

MCP_TOOLS = {"delete": "Delete", "move": "Move"}
"""troupe's tools the MCP server offers, by the effect each needs."""

UNTRANSLATABLE = "[]()*?\\"
"""Characters a path troupe roots its rules at can't hold: Claude Code reads them as pattern syntax
or as the end of the rule."""

PATTERN_UNTRANSLATABLE = "[]()\\"
"""Characters a declared pattern can't hold, beyond a leading !: ``*`` and ``?`` mean the same in
both languages."""

TEMPORARY_VARIABLES = ("TMPDIR", "TMP", "TEMP")


class EffectsRefusedError(Exception):
    """A run/start refused because of what it declares or what its options allow."""

    def __init__(self, code: str, where: str, problem: str, fix: str) -> None:
        super().__init__(f"{where}: {problem}")
        self.code = code
        self.where = where
        self.problem = problem
        self.fix = fix


@dataclass(frozen=True)
class Rules:
    """Everything the translation gives Claude Code."""

    mode: str
    allow: tuple[str, ...]
    deny: tuple[str, ...]
    add_dirs: tuple[str, ...]
    env: dict[str, str]
    mcp_tools: tuple[str, ...]
    """troupe's tools to offer through the MCP server: none, so no server, when neither delete nor
    move is declared."""
    warnings: tuple[str, ...] = field(default=())


def _tool_of(rule: str) -> str:
    return rule.split("(", 1)[0].strip()


def _untranslatable(text: str, where: str, characters: str) -> None:
    for character in characters:
        if character in text:
            raise EffectsRefusedError(
                "claude-code.untranslatable-pattern",
                where,
                f"{text!r} holds {character!r}, which Claude Code's permission rules read "
                "differently from troupe's patterns, so the rule wouldn't mean what's declared.",
                "Declare a pattern without it, such as one that matches its directory, or run "
                "the actor on a runner that checks each call (the scripted runner, or a local "
                "model's).",
            )


def _forms(path: PurePath) -> list[str]:
    """``path`` in the SDK's normalised absolute form, and its resolved form too when that differs:
    resolving only a path on this machine, never a pure one a test builds."""
    forms = [posix_absolute(path).rstrip("/")]
    if isinstance(path, Path):
        resolved = posix_absolute(path.resolve()).rstrip("/")
        if resolved not in forms:
            forms.append(resolved)
    return forms


def _rooted(path: str) -> str:
    """An absolute path in the SDK's normalised form, as a Claude Code rule's absolute path."""
    return "/" + path


class ClaudeCodePermissions:
    """The declaration as Claude Code's rules: the runner's EffectsTranslation."""

    mode: Mode = "translated"

    def __init__(self, options: Options) -> None:
        self.options = options

    def translate(self, declaration: Declaration) -> Rules:
        # Only write patterns become rules: delete and move go to troupe's own tools, which read
        # troupe's patterns as they are.
        for pattern in declaration.effects.declared("write"):
            if pattern.startswith("!"):
                _untranslatable(pattern, "effects.write", "!")
            _untranslatable(pattern, "effects.write", PATTERN_UNTRANSLATABLE)
        # Each path as given and, when a link leads elsewhere (macOS's /var is /private/var), as it
        # resolves, so a rule matches whichever form Claude Code compares.
        roots = _forms(declaration.workspace)
        for root in roots:
            _untranslatable(root, "workspace", UNTRANSLATABLE)
        write = declaration.effects.declared("write")
        allow = [f"Edit({_rooted(root)}/{pattern})" for root in roots for pattern in write]
        add_dirs: list[str] = []
        env: dict[str, str] = {}
        if declaration.scratch is not None:
            for scratch in _forms(declaration.scratch):
                _untranslatable(scratch, "scratch", UNTRANSLATABLE)
                allow.append(f"Edit({_rooted(scratch)}/**)")
            native = str(PurePath(declaration.scratch))
            add_dirs.append(native)
            env = dict.fromkeys(TEMPORARY_VARIABLES, native)
        deny = [
            f"Edit({_rooted(root)}/{entry}/**)" for root in roots for entry in (".git", ".troupe")
        ]
        offered = tuple(
            MCP_TOOLS[effect]
            for effect in ("delete", "move")
            if declaration.effects.declared(effect)
        )
        allow += [f"mcp__{MCP_SERVER}__{tool}" for tool in offered]
        return Rules(
            mode="plan" if self.options.permission_mode == "plan" else "dontAsk",
            allow=(*self.options.allowed_tools, *allow),
            deny=(*self.options.disallowed_tools, *deny),
            add_dirs=tuple(add_dirs),
            env=env,
            mcp_tools=offered,
            warnings=self._warnings(),
        )

    def _warnings(self) -> tuple[str, ...]:
        found = [
            f"allowedTools holds {rule!r}: a shell can change files the actor's effects don't "
            "declare, which the rules can't stop. troupe's audit checks the run's changes after "
            "it ends."
            for rule in self.options.allowed_tools
            if _tool_of(rule) in SHELL_TOOLS
        ]
        if self.options.setting_sources:
            sources = ", ".join(self.options.setting_sources)
            found.append(
                f"settingSources loads {sources} settings, whose permission rules Claude Code "
                "merges with the runner's: they may allow more than the actor's effects declare."
            )
        return tuple(found)


__all__ = ["MCP_TOOLS", "ClaudeCodePermissions", "EffectsRefusedError", "Rules"]
