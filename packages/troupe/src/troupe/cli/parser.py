"""Parse a command line into a command and its arguments, or a structured usage error.

Rules (spec: cli):
- Global flags are accepted anywhere, before or after the subcommand.
- A value that starts with ``-`` must come after ``--``. Without it, troupe refuses rather than
  guessing whether a value or an option was meant.
- A ``--`` with nothing after it changes nothing: the line means what it means without it.
- Unknown commands and flags are usage errors that name what wasn't recognised and suggest the
  closest valid alternative.
- Every usage shape has its own code, names the command it concerns and points at its help. A
  problem never carries a surface prefix such as ``troupe:``; the surface adds its own.

argparse does the parsing (design D2 of bootstrap-repo). troupe judges the line first: a scan
refuses unknown names and unseparated dash-leading values, because argparse on its own accepts
some as positionals (``-5``), and a check compares the line with the command's declared arguments,
because argparse reports what is missing or too much as untyped English that changes between
Python versions (argparse-errors D1). argparse then only turns an accepted line into a namespace;
if it still refuses, that is ``usage.invalid``, the backstop. argparse consumes ``--`` only
alongside positionals, so once they're filled before an option it refuses a trailing ``--``
(``status x --json --``); ``parse`` drops that separator first (status-refused D2).
"""

import argparse
import difflib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, NoReturn, TextIO

from troupe.core.errors import TroupeError
from troupe.core.exit_codes import ExitCode

HELP_FIX = "Run `troupe --help` to see the commands and options."


@dataclass(frozen=True)
class Command:
    """A subcommand: its name, one line of help, how to declare its arguments, and how to run it.
    It runs with the parsed arguments, standard output for its result, and standard error for
    progress and notices. A name of two words (``config set``) is a subcommand of a group: the
    line names the group, then the subcommand, and every rule applies to the subcommand as to any
    other."""

    name: str
    help: str
    configure: Callable[[argparse.ArgumentParser], None]
    run: Callable[[argparse.Namespace, TextIO, TextIO], ExitCode]


@dataclass(frozen=True)
class Parsed:
    show_version: bool
    command: Command | None
    arguments: argparse.Namespace
    help_text: str


class _RefusedError(Exception):
    """argparse refused the line. ``parse`` turns it into ``usage.invalid``, naming the command it
    chose, which the parser that refused can't know."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class _Parser(argparse.ArgumentParser):
    """An ArgumentParser that raises instead of printing and exiting."""

    def error(self, message: str) -> NoReturn:
        raise _RefusedError(message)


# What a command declares (design D4)


@dataclass(frozen=True)
class _Option:
    dest: str
    name: str  # the option as the help shows it, such as ``--runner``
    takes_value: bool
    required: bool
    convert: Callable[[str], Any] | None
    choices: Iterable[Any] | None


@dataclass(frozen=True)
class _Positional:
    dest: str
    name: str  # as the usage line shows it, such as ``<run>``
    least: int
    most: int | None  # None: no limit
    convert: Callable[[str], Any] | None
    choices: Iterable[Any] | None


@dataclass(frozen=True)
class _Group:
    dests: tuple[str, ...]
    required: bool


@dataclass(frozen=True)
class _Declared:
    options: tuple[_Option, ...]  # in declaration order
    strings: dict[str, _Option]  # each option by every one of its strings
    positionals: tuple[_Positional, ...]
    groups: tuple[_Group, ...]

    def name_of(self, dest: str) -> str:
        return next(option.name for option in self.options if option.dest == dest)


def _unsupported(
    parser: argparse.ArgumentParser, action: argparse.Action, what: str
) -> TroupeError:
    return TroupeError(
        "internal.unexpected",
        problem=(
            f"`{parser.prog}` declares `{'/'.join(action.option_strings) or action.dest}` with "
            f"{what}, which troupe's command-line checks can't read."
        ),
        fix="This is a bug in troupe: declare the argument in a shape parser.py supports.",
    )


def _converter(
    parser: argparse.ArgumentParser, action: argparse.Action
) -> Callable[[str], Any] | None:
    kind = action.type
    if kind is None:
        return None
    if isinstance(kind, argparse.FileType) or not callable(kind):
        # A FileType would open the file twice, once here and once in argparse (design D3).
        raise _unsupported(parser, action, f"the type {kind!r}")
    return kind


def _declared(parser: argparse.ArgumentParser) -> _Declared:
    """Everything troupe's checks need about ``parser``'s arguments. argparse keeps them private,
    so this is the one place troupe reads its internals; a test pins it to the real commands."""
    options: list[_Option] = []
    strings: dict[str, _Option] = {}
    positionals: list[_Positional] = []
    for action in parser._actions:
        if action.option_strings:
            if action.nargs not in (None, 0):
                raise _unsupported(parser, action, f"nargs={action.nargs!r}")
            longs = [string for string in action.option_strings if string.startswith("--")]
            option = _Option(
                dest=action.dest,
                name=(longs or list(action.option_strings))[0],
                takes_value=action.nargs is None,
                required=action.required,
                convert=_converter(parser, action),
                choices=action.choices if action.nargs is None else None,
            )
            options.append(option)
            for string in action.option_strings:
                strings[string] = option
        elif action.nargs == argparse.PARSER:
            continue  # the subcommand's slot, which the scan handles itself
        else:
            least, most = _counts(parser, action)
            metavar = action.metavar if isinstance(action.metavar, str) else action.dest
            positionals.append(
                _Positional(
                    dest=action.dest,
                    name=f"<{metavar}>",
                    least=least,
                    most=most,
                    convert=_converter(parser, action),
                    choices=action.choices,
                )
            )
    groups = tuple(
        _Group(tuple(action.dest for action in group._group_actions), group.required)
        for group in parser._mutually_exclusive_groups
    )
    return _Declared(tuple(options), strings, tuple(positionals), groups)


def _counts(parser: argparse.ArgumentParser, action: argparse.Action) -> tuple[int, int | None]:
    nargs = action.nargs
    if nargs is None:
        return 1, 1
    if nargs == argparse.OPTIONAL:
        return 0, 1
    if nargs == argparse.ZERO_OR_MORE:
        return 0, None
    if nargs == argparse.ONE_OR_MORE:
        return 1, None
    if isinstance(nargs, int) and nargs >= 1:
        return nargs, nargs
    raise _unsupported(parser, action, f"nargs={nargs!r}")


# The usage errors, each worded once (design D5)


def _help_fix(command: str | None) -> str:
    return HELP_FIX if command is None else f"Run `troupe {command} --help` to see its options."


def _invalid(message: str, command: str | None) -> TroupeError:
    """The backstop: argparse refused a line troupe's own checks accepted (design D7)."""
    return TroupeError(
        "usage.invalid",
        problem=message if command is None else f"`troupe {command}`: {message}",
        fix=_help_fix(command),
        details=_details(command=command),
    )


def _suggest(token: str, candidates: Sequence[str]) -> str | None:
    bare = {candidate.lstrip("-"): candidate for candidate in candidates}
    matches = difflib.get_close_matches(token.lstrip("-"), list(bare), n=1, cutoff=0.6)
    return bare[matches[0]] if matches else None


def _details(**fields: object) -> dict[str, object]:
    """A usage error's details, leaving out what it can't name: no suggestion when nothing was
    close, no command when the problem came before one (omit-nulls)."""
    return {name: value for name, value in fields.items() if value is not None}


def _looks_like_a_flag(token: str) -> bool:
    return token.startswith("--") or (
        token.startswith("-") and len(token) >= 2 and token[1].isalpha()
    )


def _is_a_value(arg: str) -> bool:
    """Whether ``token``, after an option that takes a value, is that value. argparse's own rule:
    ``--`` and flag-like tokens aren't, but text with a space is, even if it starts with ``-``
    (``--instructions "--dry-run first"``)."""
    return arg != "--" and (" " in arg or not _looks_like_a_flag(arg))


def _unknown_flag(token: str, known: Sequence[str], command: str | None) -> TroupeError:
    suggestion = _suggest(token, known)
    hint = f"Did you mean `{suggestion}`? " if suggestion else f"{_help_fix(command)} "
    where = "a troupe option" if command is None else f"an option of `troupe {command}`"
    return TroupeError(
        "usage.unknown-flag",
        problem=f"`{token}` is not {where}.",
        fix=f"{hint}If `{token}` is a value, put `--` before it.",
        details=_details(flag=token, suggestion=suggestion, command=command),
    )


def _dash_value(token: str) -> TroupeError:
    return TroupeError(
        "usage.dash-value",
        problem=f"`{token}` starts with `-`, so it is read as an option, not a value.",
        fix=f"Put `--` before values that start with `-`, for example `-- {token}`.",
        details={"value": token},
    )


def _unknown_command(token: str, commands: Sequence[Command], flags: Sequence[str]) -> TroupeError:
    names = list(dict.fromkeys(command.name.split(" ")[0] for command in commands))
    suggestion = _suggest(token, names + list(flags))
    return TroupeError(
        "usage.unknown-command",
        problem=f"`{token}` is not a troupe command."
        if token
        else ("An empty argument is not a troupe command."),
        fix=f"Did you mean `{suggestion}`?" if suggestion else HELP_FIX,
        details=_details(command=token, suggestion=suggestion),
    )


def _unknown_subcommand(group: str, token: str, names: Sequence[str]) -> TroupeError:
    suggestion = _suggest(token, list(names))
    return TroupeError(
        "usage.unknown-command",
        problem=f"`{token}` is not a `troupe {group}` command (they are: {', '.join(names)})."
        if token
        else f"An empty argument is not a `troupe {group}` command.",
        fix=f"Did you mean `troupe {group} {suggestion}`?" if suggestion else _help_fix(group),
        details=_details(command=f"{group} {token}", suggestion=suggestion),
    )


def _missing_subcommand(group: str, names: Sequence[str]) -> TroupeError:
    return TroupeError(
        "usage.missing-argument",
        problem=f"`troupe {group}` needs a command: {_either(list(names))}.",
        fix=_help_fix(group),
        details={"command": group, "argument": "command"},
    )


def _separator_before_command() -> TroupeError:
    # argparse would take the next value as the command and still read flags after it, so the
    # `--` would protect nothing. Refuse rather than guess what was meant.
    return TroupeError(
        "usage.unknown-command",
        problem="`--` comes before any command.",
        fix="Put the command first; `--` goes after it, before values that start with `-`.",
        details={"command": "--"},
    )


def _missing_value(command: str, option: str) -> TroupeError:
    return TroupeError(
        "usage.missing-value",
        problem=f"`troupe {command}` needs a value after {option}.",
        fix=(
            f"Give {option} a value, as `{option} <value>`, or as `{option}=<value>` if the "
            "value starts with `-`."
        ),
        details={"command": command, "option": option},
    )


def _either(names: Sequence[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} or {names[-1]}"


def _conflicting(command: str, options: Sequence[str]) -> TroupeError:
    return TroupeError(
        "usage.conflicting-options",
        problem=f"`troupe {command}` takes {_either(options)}, not both.",
        fix=f"Remove one of them. {_help_fix(command)}",
        details={"command": command, "options": list(options)},
    )


def _extra(command: str, value: str) -> TroupeError:
    return TroupeError(
        "usage.extra-argument",
        problem=f"`troupe {command}` got an extra value, `{value}`.",
        fix=_help_fix(command),
        details={"command": command, "value": value},
    )


def _missing(command: str, name: str, argument: str) -> TroupeError:
    return TroupeError(
        "usage.missing-argument",
        problem=f"`troupe {command}` needs {name}.",
        fix=_help_fix(command),
        details={"command": command, "argument": argument},
    )


def _missing_one_of(command: str, options: Sequence[str]) -> TroupeError:
    return TroupeError(
        "usage.missing-one-of",
        problem=f"`troupe {command}` needs one of {_either(options)}.",
        fix=_help_fix(command),
        details={"command": command, "options": list(options)},
    )


def _invalid_value(command: str, name: str, value: str) -> TroupeError:
    return TroupeError(
        "usage.invalid-value",
        problem=f"`troupe {command}` can't use `{value}` for {name}.",
        fix=f"Run `troupe {command} --help` to see what {name} takes.",
        details={"command": command, "argument": name, "value": value},
    )


# The scan and the check


@dataclass
class _Scan:
    """What the line gave: the command, the options in the order given with their raw values, the
    positional values, the first option left without a value, and where the separator is."""

    chosen: str | None = None
    group: str | None = None  # a group named, waiting for its subcommand
    given: dict[str, list[str]] = field(default_factory=dict)  # dest -> values, in line order
    positionals: list[str] = field(default_factory=list)
    without_value: str | None = None
    separator: int | None = None  # the index of the ``--`` read as the separator


def _scan(
    argv: Sequence[str],
    root: argparse.ArgumentParser,
    subparsers: dict[str, argparse.ArgumentParser],
    commands: Sequence[Command],
) -> _Scan:
    """Refuse unknown commands, unknown flags and unseparated dash-leading values, in the order the
    line meets them, and record what the line gave for the check."""
    known = _declared(root).strings
    scan = _Scan()
    at = 0
    while at < len(argv):
        arg = argv[at]
        at += 1
        if arg == "--":
            if scan.chosen is None and scan.group is not None:
                raise _missing_subcommand(scan.group, _subcommands(scan.group, commands))
            if scan.chosen is None:
                raise _separator_before_command()
            scan.separator = at - 1
            scan.positionals.extend(argv[at:])
            break
        if arg.startswith("-"):
            name, has_inline, inline = arg.partition("=") if arg.startswith("--") else (arg, "", "")
            option = known.get(name)
            if option is None:
                if _looks_like_a_flag(arg):
                    raise _unknown_flag(arg, sorted(known), scan.chosen)
                raise _dash_value(arg)
            values = scan.given.setdefault(option.dest, [])
            if not option.takes_value:
                continue
            if has_inline:
                values.append(inline)
            elif at < len(argv) and _is_a_value(argv[at]):
                values.append(argv[at])
                at += 1
            elif scan.without_value is None:
                scan.without_value = name
            continue
        if scan.chosen is None and scan.group is not None:
            name = f"{scan.group} {arg}"
            if name not in subparsers:
                raise _unknown_subcommand(scan.group, arg, _subcommands(scan.group, commands))
            scan.chosen = name
            known = _declared(subparsers[name]).strings
            continue
        if scan.chosen is None:
            if arg in _groups(commands):
                scan.group = arg
                continue
            if arg not in subparsers or " " in arg:  # a two-word command is two arguments
                raise _unknown_command(arg, commands, sorted(known))
            scan.chosen = arg
            known = _declared(subparsers[arg]).strings
            continue
        scan.positionals.append(arg)
    return scan


def _groups(commands: Sequence[Command]) -> list[str]:
    """Every group named by a two-word command, in the order first declared."""
    return list(dict.fromkeys(c.name.split(" ")[0] for c in commands if " " in c.name))


def _subcommands(group: str, commands: Sequence[Command]) -> list[str]:
    return [c.name.split(" ", 1)[1] for c in commands if c.name.startswith(f"{group} ")]


def _assign(
    positionals: Sequence[_Positional], values: Sequence[str]
) -> tuple[list[tuple[_Positional, list[str]]], list[str]]:
    """Share ``values`` among ``positionals`` in order, each taking as many as it can while
    leaving enough for those after it. Returns the shares and what is left over."""
    shares: list[tuple[_Positional, list[str]]] = []
    at = 0
    for index, positional in enumerate(positionals):
        later = sum(each.least for each in positionals[index + 1 :])
        room = max(len(values) - at - later, 0)
        take = room if positional.most is None else min(room, positional.most)
        shares.append((positional, list(values[at : at + take])))
        at += take
    return shares, list(values[at:])


def _converts(
    convert: Callable[[str], Any] | None, choices: Iterable[Any] | None, value: str
) -> bool:
    try:
        converted = value if convert is None else convert(value)
    except (argparse.ArgumentTypeError, TypeError, ValueError):
        return False
    return choices is None or converted in choices


def _check(command: str, declared: _Declared, scan: _Scan) -> None:
    """Raise the first problem with the line, in the order of design D2."""
    if scan.without_value is not None:
        raise _missing_value(command, scan.without_value)
    for group in declared.groups:
        given = [dest for dest in scan.given if dest in group.dests]
        if len(given) > 1:
            raise _conflicting(command, [declared.name_of(dest) for dest in given[:2]])
    shares, extra = _assign(declared.positionals, scan.positionals)
    if extra:
        raise _extra(command, extra[0])
    for option in declared.options:
        if option.required and option.dest not in scan.given:
            raise _missing(command, option.name, option.name)
    for positional, share in shares:
        if len(share) < positional.least:
            raise _missing(command, positional.name, positional.dest)
    for group in declared.groups:
        if group.required and not any(dest in scan.given for dest in group.dests):
            raise _missing_one_of(command, [declared.name_of(dest) for dest in group.dests])
    for option in declared.options:
        for value in scan.given.get(option.dest, []):
            if not _converts(option.convert, option.choices, value):
                raise _invalid_value(command, option.name, value)
    for positional, share in shares:
        for value in share:
            if not _converts(positional.convert, positional.choices, value):
                raise _invalid_value(command, positional.name, value)


def _global_options() -> _Parser:
    options = _Parser(add_help=False)
    # SUPPRESS: a flag missing from the subcommand's part of the line must not reset one given
    # before the subcommand.
    options.add_argument(
        "--version", action="store_true", default=argparse.SUPPRESS, help="show the version"
    )
    options.add_argument(
        "-h", "--help", action="store_true", default=argparse.SUPPRESS, help="show this help"
    )
    return options


def parse(argv: Sequence[str], commands: Sequence[Command]) -> Parsed:
    """Parse ``argv`` against ``commands``. Raises TroupeError for any usage problem."""
    global_options = _global_options()
    root = _Parser(
        prog="troupe",
        description=(
            "Run your development process with a team of agents, asking only when it needs you."
        ),
        parents=[global_options],
        add_help=False,
        allow_abbrev=False,
        exit_on_error=False,
    )
    subparsers: dict[str, argparse.ArgumentParser] = {}
    groups: dict[str, Any] = {}  # each group's own subparsers action
    if commands:
        actions = root.add_subparsers(dest="command", metavar="<command>", parser_class=_Parser)
        for each in commands:
            name, _, subcommand = each.name.partition(" ")
            target = actions
            if subcommand:
                if name not in groups:
                    group = actions.add_parser(
                        name,
                        help=f"{name}: {', '.join(_subcommands(name, commands))}",
                        description=f"troupe {name}'s commands.",
                        parents=[global_options],
                        add_help=False,
                        allow_abbrev=False,
                        exit_on_error=False,
                    )
                    subparsers[name] = group
                    groups[name] = group.add_subparsers(
                        dest=f"{name}_command", metavar="<command>", parser_class=_Parser
                    )
                target = groups[name]
            sub = target.add_parser(
                subcommand or name,
                help=each.help,
                description=each.help,
                parents=[global_options],
                add_help=False,
                allow_abbrev=False,
                exit_on_error=False,
            )
            each.configure(sub)
            subparsers[each.name] = sub

    scan = _scan(argv, root, subparsers, commands)
    if scan.given.keys() & {"help", "version"}:
        # Help and version answer before anything else, so they work on an incomplete command line.
        shown = scan.chosen if scan.chosen is not None else scan.group
        parser_for_help = subparsers[shown] if shown is not None else root
        return Parsed(
            show_version="version" in scan.given,
            command=None,
            arguments=argparse.Namespace(),
            help_text=parser_for_help.format_help(),
        )
    if scan.chosen is None and scan.group is not None:
        raise _missing_subcommand(scan.group, _subcommands(scan.group, commands))
    if scan.chosen is not None:
        _check(scan.chosen, _declared(subparsers[scan.chosen]), scan)
    # A separator with nothing after it separates nothing, and argparse would refuse it once the
    # positionals are filled before an option (design D2 of status-refused).
    trailing = scan.separator == len(argv) - 1
    try:
        arguments = root.parse_args(argv[:-1] if trailing else argv)
    except argparse.ArgumentError as error:
        raise _invalid(str(error), scan.chosen) from error
    except _RefusedError as refused:
        raise _invalid(refused.message, scan.chosen) from refused

    command = next((c for c in commands if c.name == scan.chosen), None)
    return Parsed(
        show_version=False,
        command=command,
        arguments=arguments,
        help_text=root.format_help(),
    )
