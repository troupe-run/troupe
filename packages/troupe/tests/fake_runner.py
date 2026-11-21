"""A test-only runner that misbehaves in ways the scripted runner can't, chosen by its argument.

Usage: python fake_runner.py <mode>. Not collected by pytest. Every mode ignores run/start's
options; ``ignore-options`` does nothing else unusual, for checks that a runner refuses an unknown
option. ``write-then-silent`` writes ``stray.txt`` in its working directory and then never answers.
``refuse-character`` refuses a run/start that carries a character, as a runner that treats the
contract's own field as unknown would. ``error-without-reason`` sends an error result with no
reason, which the contract refuses. ``early-initialized`` counts an initialize it refuses for its
versions as its handshake, and refuses every initialize after it. ``raw-lines`` writes each line of
the JSON list in ``FAKE_RAW_LINES`` as it is, ``{run_id}`` replaced, after ``init``, then a result
with seq ``FAKE_RAW_NEXT_SEQ`` (1 if unset); with ``FAKE_RAW_KINDS`` set it accepts
transcript-kinds. ``refuse-with-credential`` refuses every run/start with a problem holding its
``TROUPE_RUNTIME_CREDENTIAL``, as a runner that echoes its key in a refusal would.
"""

import json
import os
import subprocess
import sys
import time
from typing import Any

RUN_ID = ""
INITIALIZED = False
OK_RESULT = {"type": "result", "status": "ok", "message": "done"}
ESCAPE_CANARY = "nsecret-token-0123456789"
"""A credential that starts with n, the letter JSON's escape for a newline ends with."""


def send(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def event(seq: int, **fields: Any) -> None:  # noqa: ANN401 - event fields
    send(
        {"jsonrpc": "2.0", "method": "run/event", "params": {"runId": RUN_ID, "seq": seq, **fields}}
    )


def init() -> None:
    event(0, type="init", runner={"name": "fake", "version": "1"}, effects="checked", tools=[])


def requests() -> Any:  # noqa: ANN401 - a generator of decoded requests
    for line in sys.stdin:
        yield json.loads(line)


def answer_initialize(message: dict[str, Any], **result: Any) -> None:  # noqa: ANN401
    send(
        {
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": {
                "protocolVersion": 0,
                "runner": {"name": "fake", "version": "1"},
                "capabilities": [],
                **result,
            },
        }
    )


def main(mode: str) -> None:
    global RUN_ID
    if mode == "write-then-silent":  # changes its workspace, then never answers the handshake
        with open("stray.txt", "w", encoding="utf-8") as stray:
            stray.write("written before the handshake\n")
        mode = "silent"
    for message in requests():
        method = message.get("method")
        if mode == "silent":
            continue
        if method == "initialize":
            if mode == "early-initialized":
                # Counts a refused initialize as its handshake: refuses every later one as a second.
                code = "runner.already-initialized" if INITIALIZED else "runner.unsupported-version"
                data: dict[str, Any] = {"code": code, "problem": "No.", "fix": "Don't."}
                if not INITIALIZED and 0 not in message["params"]["protocolVersions"]:
                    data["details"] = {"supportedVersions": [0]}
                elif not INITIALIZED:
                    data = {}
                globals()["INITIALIZED"] = True
                if data:
                    send(
                        {
                            "jsonrpc": "2.0",
                            "id": message["id"],
                            "error": {"code": -32000, "message": "no", "data": data},
                        }
                    )
                else:
                    answer_initialize(message)
                continue
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
                answer_initialize(message, protocolVersion=1)
            elif mode == "capability":
                answer_initialize(message, capabilities=["resume"])
            elif mode in ("accept-transcript-kinds", "escaped-newline-credential") or (
                mode == "raw-lines" and os.environ.get("FAKE_RAW_KINDS")
            ):
                # accept-transcript-kinds: whether or not troupe offered it
                answer_initialize(message, capabilities=["transcript-kinds"])
            else:
                answer_initialize(message)
        elif method == "run/start":
            RUN_ID = message["params"]["runId"]
            refusal: dict[str, str] | None = None
            if mode == "refuse-character" and "character" in message["params"]:
                refusal = {
                    "code": "runner.invalid-params",
                    "problem": "unknown key character",
                    "fix": "Leave it out.",
                }
            if mode == "refuse-with-credential":
                key = os.environ.get("TROUPE_RUNTIME_CREDENTIAL", "")
                refusal = {
                    "code": "runner.invalid-params",
                    "problem": f"the service refused the key {key}",
                    "fix": "Use another key.",
                }
            if refusal is not None:
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "error": {"code": -32602, "message": "refused", "data": refusal},
                    }
                )
                continue
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
            if mode == "init-without-effects":
                # breaks the contract: a runner says how it applies the effects (declared-effects)
                event(0, type="init", runner={"name": "fake", "version": "1"}, tools=[])
                event(1, type="result", status="ok", message="done")
                continue
            init()
            if mode == "raw-lines":
                for raw in json.loads(os.environ["FAKE_RAW_LINES"]):
                    sys.stdout.write(raw.replace("{run_id}", RUN_ID) + "\n")
                sys.stdout.flush()
                event(int(os.environ.get("FAKE_RAW_NEXT_SEQ", "1")), **OK_RESULT)
            elif mode == "escaped-newline-credential":
                # A newline written as \u000a, then the rest of ESCAPE_CANARY: the wire line never
                # holds the credential, but JSON's own escape for the newline (\n) would.
                record = '"\\u000a' + ESCAPE_CANARY[1:] + '"'
                sys.stdout.write(
                    '{"jsonrpc": "2.0", "method": "run/transcript", "params": {"runId": "'
                    + RUN_ID
                    + '", "kind": "received", "record": '
                    + record
                    + "}}\n"
                )
                sys.stdout.flush()
                event(1, type="result", status="ok", message="done")
            elif mode == "echo-env":
                event(1, type="log", level="info", message=json.dumps(dict(os.environ)))
                event(2, type="result", status="ok", message="done")
            elif mode == "echo-argv-and-env":
                seen = {"argv": sys.argv, "env": dict(os.environ)}
                event(1, type="log", level="info", message=json.dumps(seen))
                event(2, type="result", status="ok", message="done")
            elif mode == "inspect-scratch":
                scratch = message["params"]["scratch"]
                found: dict[str, object] = {
                    "scratch": scratch,
                    "exists": os.path.isdir(scratch),
                    "empty": os.path.isdir(scratch) and not os.listdir(scratch),
                }
                with open(os.path.join(scratch, "left.txt"), "w", encoding="utf-8") as left:
                    left.write("a temporary file the run leaves behind")
                event(1, type="log", level="info", message=json.dumps(found))
                status = message["params"].get("direction") or "ok"
                reason = {"reason": "other"} if status == "error" else {}
                event(2, type="result", status=status, message="done", **reason)
            elif mode == "error-without-reason":
                # breaks the contract: an error result says why (failure-reason)
                event(1, type="result", status="error", message="API Error: 401")
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
