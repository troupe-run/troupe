"""A resolved runtime, as text (spec: runtimes; runtimes design D9).

``config get --resolved`` and a rehearsed ``perform`` both show a runtime this way: each value with
the source it came from, and a credential by its variable's name and whether that is set, never its
value.
"""

from typing import Any

from troupe.core.config_paths import shown


def runtime_lines(runtime: dict[str, Any], indent: str = "") -> list[str]:
    """The lines that show ``runtime`` (the protocol's resolved runtime)."""
    name = runtime["name"]
    lines = [f"{indent}runtime {name}"]
    endpoint = runtime["endpoint"]
    lines.append(f"{indent}  endpoint: {endpoint['value']} (from {endpoint['source']})")
    model = runtime.get("model")
    if model is not None:
        lines.append(f"{indent}  model: {model['value']} (from {model['source']})")
    else:
        variable = "TROUPE_RUNTIME_" + name.upper().replace("-", "_") + "_MODEL"
        sets = f"an actor's model, {shown(('runtimes', name, 'model'))} or {variable} sets one"
        lines.append(f"{indent}  model: none ({sets})")
    credential = runtime.get("credential")
    if credential is None:
        lines.append(f"{indent}  credential: none")
    else:
        env = credential["env"]
        state = "set" if credential["set"] else "not set"
        lines.append(
            f"{indent}  credential: from {env['value']} (named by {env['source']}), {state}"
        )
    return lines
