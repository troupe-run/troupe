"""troupe's plugin SDK: the public API plugins build against (spec: plugin-sdk; runner-sdk
design D1).

It holds the runner contract's types (``troupe_plugin_sdk.runner``, on the strict message base in
``troupe_plugin_sdk.messages``) and runs a model's tool calls in a workspace
(``troupe_plugin_sdk.tools``). Core uses the same types, so they have one definition, and plugins
depend on this package, never on core. Standard library only, and framework-free: plain functions
and immutable values.
"""
