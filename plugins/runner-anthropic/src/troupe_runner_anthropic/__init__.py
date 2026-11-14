"""troupe's Anthropic runner (spec: anthropic-runner).

It speaks the runner contract (protocol/schemas/runner/) over standard input and output, drives a
model over the Anthropic Messages API, on Claude's own API or a local engine that serves it, through
the ``anthropic`` package, and carries out each tool call the model asks for through the plugin
SDK. It imports nothing from troupe but the SDK. Run it as ``python -m troupe_runner_anthropic``.
"""

from importlib.metadata import version

NAME = "anthropic"
__version__ = version("troupe-runner-anthropic")
"""The installed package's version, so release-please's bump is what the handshake reports."""
