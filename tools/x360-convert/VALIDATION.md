# Version 0.2.0 validation — 2026-10-20

Built with Rust 1.99.1, Windows x64 GNU target, no Cargo dependencies.

## Direct folder-to-GOD regression checks

- A generated fixture with 320 variable-length names, nested/empty folders,
  empty files and a 164 MiB file crossed hash-group and fragment boundaries.
- Its direct GOD output matched every filename, byte count and SHA-256 of
  the prior version's explicit folder-to-ISO-to-GOD output.
- Left 4 Dead 2 direct GOD output matched every output file from the previous
  two-step build byte-for-byte, including the metadata header and all 28
  GOD fragments.
- Both direct packages passed full GOD hash verification.
- Direct GOD extraction restored every source file, checked by SHA-256 and
  length. Left 4 Dead 2 restored all 96 game files unchanged.
- Exporting the new Left 4 Dead 2 GOD back to ISO reproduced the exact
  previously rebuilt ISO, checked by SHA-256.
- Both conversions succeeded with the old `.building.iso` path blocked by
  a directory containing a sentinel, which remained unchanged.
- Both folder conversions reported only a `god` progress stage.
- Existing-output refusal left output files unchanged.
- Missing title metadata failed before creating output; explicit title ID
  override still produced a valid package.

## Rust unit tests

All four tests passed:

- Folder-backed reads matched an independently written ISO from the existing
  ISO writer over the entire image and 1,500 unaligned random read ranges.
  This covers directory table boundaries, multiple files, cached-file seeks,
  file-sector padding and final image alignment.
- An empty folder matched its ISO byte-for-byte.
- A source file changing size was rejected even when its handle was cached.
- SHA-1 published test vectors passed, including incremental input.

## Limits

CLI arguments, result formats and conversion output bytes are unchanged.
Folder-to-GOD progress intentionally changes from two stages to one.
These tests establish desktop file/container compatibility, not Xbox hardware
launch or gameplay. Existing format limitations remain documented in README.
