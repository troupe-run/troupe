"""A resolved runtime, as text (spec: runtimes; runtimes design D9).

``config get --resolved`` and a rehearsed ``perform`` both show a runtime this way: each value with
the source it came from, a credential by its variable's name and whether that is set, never its
value, and the model's price when the theatre prices it.
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
        where = env["value"] if "value" in env else f"the variable {env['namedBy']} names"
        lines.append(f"{indent}  credential: from {where} (named by {env['source']}), {state}")
    price = runtime.get("price")
    if price is not None:
        lines.append(f"{indent}  price: {price_text(price['value'])} (from {price['source']})")
    return lines


RATES = (("input", "input"), ("cacheRead", "cache read"), ("cacheWrite", "cache write"))


def price_text(price: dict[str, Any]) -> str:
    """``price`` in words: each rate it gives, in US dollars per million tokens."""
    rates = [(label, price[key]) for key, label in RATES if key in price]
    rates.append(("output", price["output"]))
    shown = ", ".join(f"{label} {rate:g}" for label, rate in rates)
    return f"US$ per million tokens: {shown}"
