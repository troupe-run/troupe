"""Capture a fixture for the OpenAI runner from a real Responses API service (openai-style-runner
design D13). Run by the owner, or by an agent where no working key is needed.

    # A two-turn tool loop (needs a working key for OpenAI; none for local Ollama):
    python3 -I tools/capture_openai.py loop <name> \
        --endpoint https://api.openai.com/v1 --model gpt-6-luna
    # A rejected credential, with a deliberately invalid key (free):
    python3 -I tools/capture_openai.py rejected <name> \
        --endpoint https://api.openai.com/v1 --model gpt-6-luna

The key is read from OPENAI_API_KEY for ``loop`` and never written. ``rejected`` sends a made-up
key. Each fixture directory gets ``replies.json`` (what the service answered, request by request:
a status, the headers the runner keeps, and the stream's lines or the body) and
``provenance.json``. Every string written is scrubbed of the key, any masked echo of it and the
capturing host's home directory. ``expected.json`` is written separately and reviewed by hand.
"""

import argparse
import datetime
import ipaddress
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "responses"
INVALID_KEY = "sk-troupe-capture-invalid-0000000000000000"
"""The deliberately invalid key ``rejected`` sends: it can't work, and holds nothing of anyone's."""

KEPT_HEADERS = ("retry-after", "x-request-id")
KEPT_PREFIXES = ("x-ratelimit-",)
TOOL = {
    "type": "function",
    "name": "Read",
    "description": "Read a text file in the workspace.",
    "parameters": {
        "type": "object",
        "properties": {"file_path": {"type": "string"}},
        "required": ["file_path"],
        "additionalProperties": False,
    },
    "strict": False,
}
WORKSPACE = {"notes/todo.txt": "buy milk\nwrite the troupe docs\n"}
"""The workspace a captured loop's direction is about, which the fixture's replay recreates."""


def _scrub(text: str, key: str) -> str:
    if key:
        text = text.replace(key, "[credential]")
        head, tail = re.escape(key[:4]), re.escape(key[-4:])
        echo = rf"{head}[^\s\"\\]*\*+[^\s\"\\]*|[^\s\"\\]*\*+[^\s\"\\]*{tail}"

        def masked(match: re.Match[str]) -> str:
            # The sentence's own full stop or colon after an echo isn't part of it.
            token = match.group(0)
            core = token.rstrip(".:")
            return "[credential]" + token[len(core) :]

        text = re.sub(echo, masked, text)
    return text.replace(str(Path.home()), "~")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuses every redirect, so the key is never resent to another host, as the runner does."""

    def redirect_request(self, *_: Any) -> None:  # noqa: ANN401
        return None


def _local(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def _post(base: str, body: dict[str, Any], key: str) -> dict[str, Any]:
    parts = urllib.parse.urlsplit(base)
    if key and parts.scheme != "https" and not _local(parts.hostname or ""):
        raise SystemExit(f"Refusing to send a key over plain http to {base}: use https.")
    opener = urllib.request.build_opener(_NoRedirect())
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(  # noqa: S310 - an endpoint the capturer names
        base.rstrip("/") + "/responses", json.dumps(body).encode(), headers, method="POST"
    )
    try:
        with opener.open(request, timeout=180) as response:
            status, raw, got = response.status, response.read(), response.headers
    except urllib.error.HTTPError as error:
        status, raw, got = error.code, error.read(), error.headers
    kept = [
        [name.lower(), value]
        for name, value in got.items()
        if name.lower() in KEPT_HEADERS or name.lower().startswith(KEPT_PREFIXES)
    ]
    text = _scrub(raw.decode("utf-8"), key)
    reply: dict[str, Any] = {"status": status, "headers": kept}
    if status == 200:
        reply["lines"] = text.split("\n")
        if reply["lines"] and reply["lines"][-1] == "":
            reply["lines"].pop()
    else:
        reply["body"] = text
    return reply


def _completed(reply: dict[str, Any]) -> dict[str, Any] | None:
    for line in reply.get("lines", []):
        if line.startswith("data: ") and '"response.completed"' in line:
            found: dict[str, Any] = json.loads(line[6:])["response"]
            return found
    return None


def _write(name: str, replies: list[dict[str, Any]], provenance: dict[str, Any]) -> Path:
    directory = FIXTURES / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "replies.json").write_text(json.dumps(replies, indent=2) + "\n", encoding="utf-8")
    (directory / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )
    return directory


def loop(name: str, endpoint: str, model: str) -> Path:
    key = os.environ.get("OPENAI_API_KEY", "")
    first = {
        "model": model,
        "instructions": "You work in a workspace only through the tools offered.",
        "input": [
            {
                "role": "user",
                "content": "Read notes/todo.txt, then tell me in one line what it says.",
            }
        ],
        "tools": [TOOL],
        "stream": True,
        "store": False,
        "include": ["reasoning.encrypted_content"],
        "max_output_tokens": 400,
    }
    replies = [_post(endpoint, first, key)]
    response = _completed(replies[0])
    if response is None:
        raise SystemExit("The first reply has no response.completed; nothing to continue.")
    calls = [item for item in response["output"] if item.get("type") == "function_call"]
    outputs = [
        {
            "type": "function_call_output",
            "call_id": call["call_id"],
            "output": "1\tbuy milk\n2\twrite the troupe docs",
        }
        for call in calls
    ]
    second = {**first, "input": first["input"] + response["output"] + outputs}
    replies.append(_post(endpoint, second, key))
    return _write(
        name,
        replies,
        {
            "service": endpoint,
            "model": model,
            "captured": datetime.date.today().isoformat(),
            "how": "recorded with tools/capture_openai.py loop",
            "credential": "a working key from OPENAI_API_KEY, never written" if key else "none",
            "workspace": WORKSPACE,
        },
    )


def rejected(name: str, endpoint: str, model: str) -> Path:
    body = {"model": model, "input": "hello", "stream": True, "store": False}
    return _write(
        name,
        [_post(endpoint, body, INVALID_KEY)],
        {
            "service": endpoint,
            "model": model,
            "captured": datetime.date.today().isoformat(),
            "how": "recorded with tools/capture_openai.py rejected",
            "credential": "a deliberately invalid key; no working credential was used",
        },
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("kind", choices=["loop", "rejected"])
    parser.add_argument("name")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args(argv)
    made = (loop if args.kind == "loop" else rejected)(args.name, args.endpoint, args.model)
    print(f"wrote {made}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
