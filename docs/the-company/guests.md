---
title: Guests
description: Installable packs.
status: written
prerelease: true
---

A guest is an installable pack that adds to troupe. Guests aren't built yet, and most of what they are isn't decided.
"Guest" is the name for now.

## What's decided

- **Guests keep their own files, in their own places,** with the schemas they bring. troupe recognises a guest's
  files by their paths, the same way it recognises its own, so a guest can add to your config without reshaping
  troupe's.
- **A guest acquired through config runs as a separate process,** speaking JSON-RPC to troupe, never inside it.

## Not decided yet

How guests are named, pinned, fetched and checked isn't decided. The leaning is for config to name each one with
its version, and a lock file to hold its hash, but that's still open, in
[#38](https://github.com/troupe-run/troupe/issues/38) and [#67](https://github.com/troupe-run/troupe/issues/67).

What a guest can add, what its manifest holds, how one is written, tested and published, and how a guest relates to a
plugin: all of these are open, in [#127](https://github.com/troupe-run/troupe/issues/127). See [Write a
guest](../stagecraft/write-a-guest.md) and the [guest manifest](../prompt-book/guest-manifest.md).
