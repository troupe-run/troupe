"""troupe's Ollama runner (spec: ollama-runner).

It speaks the runner contract (protocol/schemas/runner/) over standard input and output, and
drives a model served by Ollama through Ollama's own ``/api/chat``, with troupe's own tool loop:
each tool call the model makes is carried out by the plugin SDK's tools, checked against the
actor's declared effects. It imports nothing of troupe's but the SDK. Run it as
``python -m troupe_runner_ollama``.
"""

from importlib.metadata import version

NAME = "ollama"
"""The runner's name, in its answer to initialize and its init event."""

__version__ = version("troupe-runner-ollama")
"""The installed package's version, so the runner reports what's installed."""
