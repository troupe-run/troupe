"""troupe's LM Studio runner (spec: lm-studio-runner).

It speaks the runner contract (protocol/schemas/runner/) over standard input and output, drives a
model in LM Studio through LM Studio's own client library, ``lmstudio``, and carries out each tool
call the library asks for through the plugin SDK. It imports nothing from troupe but the SDK. Run it
as ``python -m troupe_runner_lm_studio``.
"""

from importlib.metadata import version

NAME = "lm-studio"
__version__ = version("troupe-runner-lm-studio")
"""The installed package's version, so release-please's bump is what the handshake reports."""
