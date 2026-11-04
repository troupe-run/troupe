"""troupe's OpenAI-style runner (spec: openai-chat-runner).

It speaks the runner contract (protocol/schemas/runner/) over standard input and output, drives a
service that speaks the OpenAI-style Chat Completions API, and carries out the model's tool calls
itself through the plugin SDK. It imports nothing from troupe but the SDK. Run it as
``python -m troupe_runner_openai_chat``.
"""

NAME = "openai-chat"
__version__ = "0.0.0"
