"""Running a short external command for an adapter (event-store design D11).

Thin wrapper over troupe.platform.processes.run_to_completion: the child gets exactly the
environment its adapter's policy selects, and platform failures become TroupeErrors with a code, the
problem and the fix. Adapters declare their own policy and limits as named defaults in their own
package; core knows none of them.
"""

import os
import shlex
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from troupe.core.errors import TroupeError
from troupe.platform.errors import (
    CommandNotFoundError,
    EnvironmentPolicyError,
    OutputTooLargeError,
    ProcessTimeoutError,
)
from troupe.platform.processes import (
    Completed,
    EnvironmentPolicy,
    ProcessWaitCallback,
    build_environment,
    run_to_completion,
)


def run_command(
    argv: Sequence[str],
    *,
    cwd: str | os.PathLike[str],
    policy: EnvironmentPolicy,
    timeout: float,
    max_output_bytes: int,
    announce_after: float,
    source: Mapping[str, str] | None = None,
    on_wait: ProcessWaitCallback | None = None,
) -> Completed:
    """Run ``argv`` to completion in ``cwd`` with the environment ``policy`` selects from
    ``source`` (troupe's own environment when omitted)."""
    shown = shlex.join(argv)
    where = str(Path(cwd).absolute())
    try:
        env = build_environment(policy, source=source)
    except EnvironmentPolicyError as error:
        raise policy_error(error) from error
    parent = os.environ if source is None else source
    try:
        return run_to_completion(
            argv,
            cwd=cwd,
            env=env,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
            announce_after=announce_after,
            on_wait=on_wait,
            search_path=parent.get("PATH", ""),
        )
    except CommandNotFoundError as error:
        raise TroupeError(
            "command.not-found",
            problem=f"Couldn't run {shown}: {argv[0]!r} wasn't found on the path.",
            fix=f"Install {argv[0]}, or put the directory that holds it on PATH, then try again.",
            path=where,
            details={"command": shown},
        ) from error
    except ProcessTimeoutError as error:
        raise TroupeError(
            "command.timeout",
            problem=f"{shown} was still running after {error.timeout:g}s, so it and every process "
            "it started were stopped.",
            fix="Check for something holding the command up, such as a hook or a prompt, or raise "
            "the timeout setting for this command.",
            path=where,
            details={"command": shown, "timeoutSeconds": error.timeout},
        ) from error
    except OutputTooLargeError as error:
        raise TroupeError(
            "command.output-too-large",
            problem=f"{shown} wrote more than {error.limit} bytes, so it was stopped.",
            fix="Check why the command produced so much output, or raise the output limit "
            "setting for this command.",
            path=where,
            details={"command": shown, "limitBytes": error.limit},
        ) from error


def narrow_policy(
    policy: EnvironmentPolicy,
    *,
    names: Iterable[str] | None = None,
    prefixes: Iterable[str] | None = None,
    never: Iterable[str] = (),
    never_prefixes: Iterable[str] = (),
) -> EnvironmentPolicy:
    """``policy`` narrowed: fewer names or prefixes, or more exclusions. Widening is refused with
    environment.policy-invalid."""
    try:
        return policy.narrow(
            names=names, prefixes=prefixes, never=never, never_prefixes=never_prefixes
        )
    except EnvironmentPolicyError as error:
        raise policy_error(error) from error


def policy_error(error: EnvironmentPolicyError) -> TroupeError:
    """An environment policy that was narrowed wrongly, or an explicit value it forbids."""
    return TroupeError(
        "environment.policy-invalid",
        problem=f"The environment variable {error.name!r} can't be passed this way: "
        f"{error.reason}.",
        fix="A policy can only be narrowed: select fewer names or prefixes, or add exclusions. "
        "Remove the widening, or change the adapter's default policy itself.",
        details={"name": error.name, "reason": error.reason},
    )
