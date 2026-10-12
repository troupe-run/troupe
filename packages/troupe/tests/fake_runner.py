"""A test-only runner that misbehaves in ways the scripted runner can't, chosen by its argument.

Usage: python fake_runner.py <mode>. Not collected by pytest.
"""

import json
import os
import subprocess
import sys
import time
from typing import Any

RUN_ID = ""


def send(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def event(seq: int, **fields: Any) -> None:  # noqa: ANN401 - event fields
    send(
        {"jsonrpc": "2.0", "method": "run/event", "params": {"runId": RUN_ID, "seq": seq, **fields}}
    )


def init() -> None:
    event(0, type="init", runner={"name": "fake", "version": "1"}, tools=[])


def requests() -> Any:  # noqa: ANN401 - a generator of decoded requests
    for line in sys.stdin:
        yield json.loads(line)


def answer_initialize(message: dict[str, Any], **result: Any) -> None:  # noqa: ANN401
    send(
        {
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": {
                "protocolVersion": 1,
                "runner": {"name": "fake", "version": "1"},
                "capabilities": [],
                **result,
            },
        }
    )


def main(mode: str) -> None:
    global RUN_ID
    for message in requests():
        method = message.get("method")
        if mode == "silent":
            continue
        if method == "initialize":
            if mode == "incompatible":
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "error": {
                            "code": -32000,
                            "message": "no",
                            "data": {
                                "code": "runner.unsupported-version",
                                "problem": "Only version 9.",
                                "fix": "Offer version 9.",
                                "details": {"supportedVersions": [9]},
                            },
                        },
                    }
                )
                return
            if mode == "wrong-version":
                answer_initialize(message, protocolVersion=2)
            elif mode == "capability":
                answer_initialize(message, capabilities=["resume"])
            else:
                answer_initialize(message)
        elif method == "run/start":
            RUN_ID = message["params"]["runId"]
            if mode == "wrong-run-id":
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "result": {"runId": "11111111-1111-4111-8111-111111111111"},
                    }
                )
                continue
            send({"jsonrpc": "2.0", "id": message["id"], "result": {"runId": RUN_ID}})
            init()
            if mode == "echo-env":
                event(1, type="log", level="info", message=json.dumps(dict(os.environ)))
                event(2, type="result", status="ok", message="done")
            elif mode == "ignore-shutdown":
                event(1, type="result", status="ok", message="done")
            elif mode == "unsent-id":
                send({"jsonrpc": "2.0", "id": 99, "result": {}})
            elif mode == "ignore-cancel-with-child":
                child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
                event(1, type="log", level="info", message=str(child.pid))
        elif method == "run/cancel":
            send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
            if mode != "ignore-cancel-with-child":
                return
        elif method == "shutdown":
            if mode == "ignore-shutdown":
                time.sleep(120)
            send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
            return


if __name__ == "__main__":
    main(sys.argv[1])
    if sys.argv[1] == "ignore-eof":
        time.sleep(120)  # breaks the contract: a runner exits when its input closes
