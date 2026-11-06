"""troupe's OpenAI runner (spec: openai-runner).

It speaks the runner contract (protocol/schemas/runner/) over standard input and output, drives a
service that serves OpenAI's Responses API, and carries out the model's tool calls
itself through the plugin SDK. It imports nothing from troupe but the SDK. Run it as
``python -m troupe_runner_openai``.
"""

NAME = "openai"
__version__ = "0.0.0"
