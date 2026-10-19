---
title: Guest manifest
description: Guest manifest reference.
status: written
prerelease: true
---

This page will be the reference for the guest manifest: the file that says what a guest is and what it adds. Its
format isn't decided yet: it's open in [#127](https://github.com/troupe-run/troupe/issues/127).

What's decided is that a guest brings its own files and the schemas for them, and troupe recognises them by their
paths, and that every file troupe reads has a JSON Schema, as [config](config-schema.md) does. See
[Guests](../the-company/guests.md).
