# 0.2.0 — 2026-10-20

- Extracted folder to GOD now streams directly from a planned disc layout.
  No temporary ISO is written or read back.
- Keeps the same deterministic directory ordering, sector addresses, padding,
  GOD block hashes and metadata as the earlier two-step conversion.
- Preserves the existing commands, arguments, exit codes and output formats.
  Folder-to-GOD progress has one `god` stage rather than `iso` followed by `god`.
- Source file-size changes are checked when opening and reading cached files.
- Adds layout tests for unaligned reads, random seeks, empty directories,
  sector padding, changed source sizes and out-of-bounds requests.
- Adds complete-package comparisons against version 0.1.0 and a blocked
  intermediate-path regression test.

The converter source remains 0BSD with no third-party Cargo dependencies.
This update is separate from the GPL-licensed VTFEdit extension project.
