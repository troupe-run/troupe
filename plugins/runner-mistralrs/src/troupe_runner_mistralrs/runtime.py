"""The run's runtime and its model file (spec: mistralrs-runner, "The model comes from the run's
in-process runtime", "The model is a local GGUF file"; in-process-runner design D5).

The runtime is troupe's built-in in-process ``mistralrs``: no endpoint, no credential, and a model
that is the absolute path of a GGUF file on this machine. Everything here is checked before the run
is acknowledged, quickly, without loading anything. The credential's variable is never read.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from troupe_plugin_sdk.runner import RunStartParams

GGUF_SIGNATURE = b"GGUF"
"""The four bytes every GGUF file starts with."""

MODEL_VARIABLE = "TROUPE_RUNTIME_MISTRALRS_MODEL"
"""Where a person points the built-in runtime at their model file."""


class RuntimeRefusedError(Exception):
    """run/start's runtime refused, with the code, where it is, the problem, the fix, and the
    error's details."""

    def __init__(
        self, code: str, where: str, problem: str, fix: str, details: dict[str, str] | None = None
    ) -> None:
        super().__init__(f"{where}: {problem}")
        self.code = code
        self.where = where
        self.problem = problem
        self.fix = fix
        self.details = details if details is not None else {"where": where}


@dataclass(frozen=True)
class Runtime:
    """The run's model, as the runner loads it."""

    name: str
    model: Path
    """The model file: an absolute path to an existing GGUF file."""


def _model_fix() -> str:
    return (
        f"Set {MODEL_VARIABLE}, or the actor's model, to the absolute path of a GGUF file on this "
        "machine, such as /Users/you/models/qwen3-0.6b-q8_0.gguf."
    )


def from_run_start(params: RunStartParams) -> Runtime:
    """The run's runtime. Refused when run/start names none, when it has an endpoint or a
    credential, and when its model isn't an absolute path to a readable GGUF file. Nothing is
    loaded, and nothing is fetched."""
    runtime = params.runtime
    if runtime is None:
        raise RuntimeRefusedError(
            "mistralrs.no-runtime",
            "runtime",
            "run/start names no runtime, so the mistralrs runner has no model to load.",
            "Name the built-in runtime for the actor (troupe config set "
            f"actors.<name>.runtime=mistralrs), and point {MODEL_VARIABLE} at a GGUF file.",
        )
    if runtime.endpoint is not None:
        raise RuntimeRefusedError(
            "mistralrs.invalid-runtime",
            "runtime.endpoint",
            f"The runtime {runtime.name!r} has an endpoint, but the mistralrs runner loads its "
            "model in its own process and talks to no service.",
            "Name the built-in in-process runtime for the actor (troupe config set "
            "actors.<name>.runtime=mistralrs).",
        )
    if runtime.credential:
        raise RuntimeRefusedError(
            "mistralrs.invalid-runtime",
            "runtime.credential",
            f"The runtime {runtime.name!r} has a credential, but the mistralrs runner loads its "
            "model in its own process and sends no credential anywhere.",
            "Name the built-in in-process runtime for the actor (troupe config set "
            "actors.<name>.runtime=mistralrs), which has none.",
        )
    return Runtime(runtime.name, checked_model(runtime.model))


def checked_model(model: str) -> Path:
    """``model`` as the file to load: refused unless it's an absolute path to an existing file
    that starts with the GGUF signature."""
    path = Path(model)
    details = {"where": "runtime.model", "model": model}
    if not path.is_absolute():
        raise RuntimeRefusedError(
            "mistralrs.invalid-model",
            "runtime.model",
            f"The run's model, {model!r}, isn't an absolute path: the mistralrs runner loads a "
            "GGUF file on this machine, and never fetches a model by its name.",
            _model_fix(),
            details,
        )
    try:
        with path.open("rb") as file:
            signature = file.read(len(GGUF_SIGNATURE))
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError, PermissionError) as error:
        why = "there's no such file" if isinstance(error, FileNotFoundError) else "it can't be read"
        raise RuntimeRefusedError(
            "mistralrs.model-not-found",
            "runtime.model",
            f"The run's model, {model}, can't be loaded: {why}.",
            _model_fix(),
            details,
        ) from None
    except OSError as error:
        raise RuntimeRefusedError(
            "mistralrs.model-not-found",
            "runtime.model",
            f"The run's model, {model}, can't be read: {os.strerror(error.errno or 0)}.",
            _model_fix(),
            details,
        ) from None
    if signature != GGUF_SIGNATURE:
        raise RuntimeRefusedError(
            "mistralrs.invalid-model",
            "runtime.model",
            f"The run's model, {model}, isn't a GGUF file: it doesn't start with the GGUF "
            "signature.",
            _model_fix(),
            details,
        )
    return path


__all__ = ["MODEL_VARIABLE", "Runtime", "RuntimeRefusedError", "checked_model", "from_run_start"]
