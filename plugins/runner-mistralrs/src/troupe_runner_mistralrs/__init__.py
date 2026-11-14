"""troupe's in-process runner (spec: mistralrs-runner).

It speaks the runner contract (protocol/schemas/runner/) over standard input and output, loads a
GGUF model inside its own process with mistral.rs's Python package, ``mistralrs``, and drives it
with troupe's own tool loop, carrying out each tool call through the plugin SDK. There is no server
and no network. It imports nothing from troupe but the SDK. Run it as
``python -m troupe_runner_mistralrs``.

Importing this package never imports ``mistralrs``: the entry point moves file descriptor 1 off
the protocol channel first, since the engine writes its log lines there (design D3).
"""

from importlib.metadata import version

NAME = "mistralrs"
__version__ = version("troupe-runner-mistralrs")
"""The installed package's version, so release-please's bump is what the handshake reports."""
