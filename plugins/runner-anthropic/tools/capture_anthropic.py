"""Capture a fixture for the Anthropic runner from a real Messages API service (anthropic-runner
design D12). Run by the owner for Claude's API, or by an agent against a local engine or with a
deliberately invalid key.

    # A tool loop (needs a working key for Claude's API; none for a local engine):
    python3 -I tools/capture_anthropic.py loop <name> --endpoint <base> --model <model>
    # A prompt longer than the model's context, refused or cut (free: a refusal isn't billed):
    python3 -I tools/capture_anthropic.py context <name> --endpoint <base> --model <model> --words N
    # A tool loop whose results outgrow the context (a local engine):
    python3 -I tools/capture_anthropic.py outgrow <name> --endpoint <base> --model <model> --words N
    # A reply cut by its output limit:
    python3 -I tools/capture_anthropic.py output-limit <name> --endpoint <base> --model <model>
    # A rejected credential, with a deliberately invalid key (free):
    python3 -I tools/capture_anthropic.py rejected <name> --endpoint https://api.anthropic.com \
        --model <model>

The key is read from ANTHROPIC_API_KEY and never written; without it, a capture from a service that
isn't on this machine stops before sending anything. ``rejected`` sends a made-up key, and a local
engine needs none. The tool speaks the Messages API with the standard library, as the runner's
library sends it (the same ``anthropic-version``), streamed, and follows no redirect. Each fixture
directory gets ``replies.json`` (what the service answered, request by request: a status, the
headers the runner keeps, and the stream's lines or the body) and ``provenance.json``. Every string
written is scrubbed of the key, any masked echo of it, request ids, and the capturing host's home
directory. ``expected.json`` is written separately, from a replay, and reviewed by hand.
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

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
INVALID_KEY = "sk-ant-troupe-capture-invalid-0000000000000000"
"""The deliberately invalid key ``rejected`` sends: it can't work, and holds nothing of anyone's."""
API_VERSION = "2026-10-21"
"""The anthropic-version the runner's library (anthropic 2.8.0) sends."""

KEPT_HEADERS = ("content-type", "request-id", "retry-after", "retry-after-ms", "x-should-retry")
KEPT_PREFIXES = ("anthropic-ratelimit-",)
SYSTEM = "You work in a workspace only through the tools offered."
TOOL = {
    "name": "Read",
    "description": "Read a text file in the workspace.",
    "input_schema": {
        "type": "object",
        "properties": {"file_path": {"type": "string"}},
        "required": ["file_path"],
        "additionalProperties": False,
    },
}
WORKSPACE = {"notes/todo.txt": "buy milk\nwrite the troupe docs\n"}
"""The workspace a captured loop's direction is about, which the fixture's replay recreates."""
LOOP_DIRECTION = "Read notes/todo.txt, then tell me in one line what it says."
MAX_REQUESTS = 8
"""The most requests a captured loop sends, so a model that keeps calling tools costs little."""


def _scrub(text: str, key: str) -> str:
    if key:
        text = text.replace(key, "[credential]")
        head, tail = re.escape(key[:6]), re.escape(key[-4:])
        echo = rf"{head}[^\s\"\\]*\*+[^\s\"\\]*|[^\s\"\\]*\*+[^\s\"\\]*{tail}"

        def masked(match: re.Match[str]) -> str:
            token = match.group(0)
            core = token.rstrip(".:")
            return "[credential]" + token[len(core) :]

        text = re.sub(echo, masked, text)
    text = re.sub(r"req_[A-Za-z0-9]+", "req_scrubbed", text)
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
    proxies = urllib.request.ProxyHandler({} if _local(parts.hostname or "") else None)
    opener = urllib.request.build_opener(proxies, _NoRedirect())
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "anthropic-version": API_VERSION,
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(  # noqa: S310 - an endpoint the capturer names
        base.rstrip("/") + "/v1/messages", json.dumps(body).encode(), headers, method="POST"
    )
    try:
        with opener.open(request, timeout=600) as response:
            status, raw, got = response.status, response.read(), response.headers
    except urllib.error.HTTPError as error:
        status, raw, got = error.code, error.read(), error.headers
    kept = [
        [name.lower(), value]
        for name, value in got.items()
        if name.lower() in KEPT_HEADERS or name.lower().startswith(KEPT_PREFIXES)
    ]
    text = _scrub(raw.decode("utf-8"), key)
    kept = [[name, _scrub(value, key)] for name, value in kept]
    reply: dict[str, Any] = {"status": status, "headers": kept}
    if status == 200 and "text/event-stream" in (got.get("content-type") or ""):
        reply["lines"] = text.replace("\r\n", "\n").split("\n")
        if reply["lines"] and reply["lines"][-1] == "":
            reply["lines"].pop()
    else:
        reply["body"] = text
    return reply


def _message(reply: dict[str, Any]) -> dict[str, Any] | None:
    """The reply's message, gathered from its stream: its content blocks and stop reason."""
    message: dict[str, Any] | None = None
    blocks: dict[int, dict[str, Any]] = {}
    json_text: dict[int, str] = {}
    for line in reply.get("lines", []):
        if not line.startswith("data: "):
            continue
        event = json.loads(line[6:])
        kind = event.get("type")
        if kind == "message_start":
            message = event["message"]
        elif kind == "content_block_start":
            blocks[event["index"]] = dict(event["content_block"])
        elif kind == "content_block_delta":
            delta, block = event["delta"], blocks[event["index"]]
            if delta["type"] == "text_delta":
                block["text"] = block.get("text", "") + delta["text"]
            elif delta["type"] == "input_json_delta":
                json_text[event["index"]] = (
                    json_text.get(event["index"], "") + delta["partial_json"]
                )
            elif delta["type"] == "thinking_delta":
                block["thinking"] = block.get("thinking", "") + delta["thinking"]
            elif delta["type"] == "signature_delta":
                block["signature"] = block.get("signature", "") + delta["signature"]
        elif kind == "message_delta" and message is not None:
            message["stop_reason"] = event["delta"].get("stop_reason")
    if message is None:
        return None
    for index, text in json_text.items():
        blocks[index]["input"] = json.loads(text) if text.strip() else {}
    message["content"] = [blocks[index] for index in sorted(blocks)]
    return message


def _write(name: str, replies: list[dict[str, Any]], provenance: dict[str, Any]) -> Path:
    directory = FIXTURES / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "replies.json").write_text(json.dumps(replies, indent=2) + "\n", encoding="utf-8")
    (directory / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )
    return directory


def _provenance(endpoint: str, model: str, how: str, key: str, **more: Any) -> dict[str, Any]:  # noqa: ANN401
    return {
        "service": endpoint,
        "model": model,
        "captured": datetime.date.today().isoformat(),
        "how": f"recorded with tools/capture_anthropic.py {how}",
        "credential": "a working key from ANTHROPIC_API_KEY, never written" if key else "none",
        **more,
    }


def _loop(
    endpoint: str, model: str, key: str, direction: str, files: dict[str, str], max_tokens: int
) -> list[dict[str, Any]]:
    """A tool loop that answers each Read from ``files``, until the model stops calling tools."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": direction}]
    replies: list[dict[str, Any]] = []
    for _ in range(MAX_REQUESTS):
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "system": SYSTEM,
            "messages": messages,
            "tools": [TOOL],
            "stream": True,
        }
        reply = _post(endpoint, body, key)
        replies.append(reply)
        message = _message(reply)
        if message is None or message.get("stop_reason") != "tool_use":
            break
        uses = [block for block in message["content"] if block.get("type") == "tool_use"]
        results = [
            {
                "type": "tool_result",
                "tool_use_id": use["id"],
                "content": files.get(
                    str(use.get("input", {}).get("file_path", "")), "There's no such file."
                ),
            }
            for use in uses
        ]
        messages += [
            {"role": "assistant", "content": message["content"]},
            {"role": "user", "content": results},
        ]
    return replies


def _key(endpoint: str) -> str:
    """The key from ANTHROPIC_API_KEY. A service that isn't on this machine needs one, so its
    absence stops the capture, rather than recording a 401 as the fixture."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key and not _local(urllib.parse.urlsplit(endpoint).hostname or ""):
        raise SystemExit(
            f"ANTHROPIC_API_KEY isn't set, and {endpoint} needs a key: set it in this shell and "
            "run again. Nothing was written."
        )
    return key


def loop(name: str, endpoint: str, model: str, _: int) -> Path:
    key = _key(endpoint)
    replies = _loop(endpoint, model, key, LOOP_DIRECTION, WORKSPACE, 400)
    return _write(name, replies, _provenance(endpoint, model, "loop", key, workspace=WORKSPACE))


def _filler(words: int, seed: int = 0) -> str:
    return " ".join(f"w{(seed * 7 + n) % 89}" for n in range(words))


def context(name: str, endpoint: str, model: str, words: int) -> Path:
    key = _key(endpoint)
    body = {
        "model": model,
        "max_tokens": 64,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": _filler(words) + "\n\nSay done."}],
        "stream": True,
    }
    return _write(
        name,
        [_post(endpoint, body, key)],
        _provenance(endpoint, model, f"context ({words} words)", key),
    )


def outgrow(name: str, endpoint: str, model: str, words: int) -> Path:
    key = _key(endpoint)
    files = {f"parts/part{n}.txt": _filler(words, n) for n in range(1, 7)}
    direction = (
        "Read parts/part1.txt, then parts/part2.txt, and so on up to parts/part6.txt, one file "
        "per tool call, then tell me how many files you read."
    )
    replies = _loop(endpoint, model, key, direction, files, 2000)
    return _write(
        name,
        replies,
        _provenance(endpoint, model, f"outgrow ({words} words a file)", key, workspace=files),
    )


def output_limit(name: str, endpoint: str, model: str, _: int) -> Path:
    key = _key(endpoint)
    body = {
        "model": model,
        "max_tokens": 5,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": "Count from 1 to 50, one number a line."}],
        "stream": True,
    }
    return _write(
        name, [_post(endpoint, body, key)], _provenance(endpoint, model, "output-limit", key)
    )


def rejected(name: str, endpoint: str, model: str, _: int) -> Path:
    body = {
        "model": model,
        "max_tokens": 16,
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
    }
    provenance = _provenance(endpoint, model, "rejected", "")
    provenance["credential"] = "a deliberately invalid key; no working credential was used"
    return _write(name, [_post(endpoint, body, INVALID_KEY)], provenance)


KINDS = {
    "loop": loop,
    "context": context,
    "outgrow": outgrow,
    "output-limit": output_limit,
    "rejected": rejected,
}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("kind", choices=sorted(KINDS))
    parser.add_argument("name")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--words", type=int, default=12_000)
    args = parser.parse_args(argv)
    made = KINDS[args.kind](args.name, args.endpoint, args.model, args.words)
    print(f"wrote {made}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
