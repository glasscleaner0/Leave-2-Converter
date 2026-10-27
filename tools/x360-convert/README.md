# x360-convert 0.2.0

Independent Rust command-line converter for Xbox 360 game containers. Windows
x64 preview build. No God2Iso, Iso2God or Exiso executable, source code,
decompiled code, interface asset, or embedded template is included or invoked
by the converter. There are no third-party Cargo dependencies.

Version 0.2 streams extracted folders straight into GOD output. It plans the
disc directory layout in memory and reads the source files on demand; no
temporary ISO is created. GOD-to-folder extraction was already direct.
All CLI conversion routes now avoid complete intermediate conversion files.

## Conversions

| Input | ISO | Extracted game folder | GOD |
| --- | --- | --- | --- |
| GOD package file | `iso` | `extract` | — |
| Xbox ISO | — | `extract` | `god` |
| Extracted game folder | `iso` | — | `god` |

Separate LIVE/PIRS STFS DLC packages can be listed and extracted with
`list-dlc` and `extract-dlc`. They are not disc images. DLC is not silently
merged into the base game or repackaged as GOD.

```powershell
.\bin\x360-convert.exe inspect "D:\Games\game-package"
.\bin\x360-convert.exe extract "D:\Games\game-package" "D:\Games\Extracted"
.\bin\x360-convert.exe iso "D:\Games\game-package" "D:\Games\Game.iso"
.\bin\x360-convert.exe iso "D:\Games\Extracted" "D:\Games\Rebuilt.iso"
.\bin\x360-convert.exe god "D:\Games\Game.iso" "D:\Games\NewGOD" --title "Left 4 Dead 2"
.\bin\x360-convert.exe god "D:\Games\Extracted" "D:\Games\FolderGOD" --title "Left 4 Dead 2"
.\bin\x360-convert.exe verify-god "D:\Games\NewGOD\PACKAGE_FILENAME"
.\bin\x360-convert.exe extract-dlc "D:\Games\DLC_PACKAGE" "D:\Games\DLCFiles"
```

Pass the small GOD package file, not its `.data` directory or a `Data0000`
fragment. Keep the matching `.data` directory alongside the package.

`god` creates a new output directory containing the package file and matching
`.data` directory. For dashboard placement, copy those two items into the
appropriate `Content\0000000000000000\TITLEID\00007000` directory yourself.
The title ID, media ID, versions and disc metadata are read from `default.xex`.
Supply `--title-id 454108D4` when a title ID cannot be obtained from the XEX.
The display title defaults to `Xbox 360 Game`; set `--title` explicitly.

## GUI integration

Launch as a child process with an argument array. Capture stdout and stderr
separately and stream both; do not wait while leaving either pipe undrained.
No prompts or interactive windows are used.

- Exit code `0`: success. Exit code `1`: an error occurred.
- stderr: `progress<TAB>stage<TAB>bytes_done<TAB>bytes_total`.
- stderr on failure: `error<TAB>message`.
- stdout on conversion success: `complete<TAB>output_path`.
- GOD creation also emits `package<TAB>package_path` on stdout.
- `list` / `list-dlc`: `file|dir<TAB>byte_size<TAB>relative_path`.
- `manifest`: `sha1<TAB>byte_size<TAB>relative_path`, one line per file.
- `inspect`: tab-separated key/value lines.
- `verify-god`: `verified<TAB>fragment_count<TAB>data_bytes`.
- `--quiet` suppresses progress. Other result/error lines remain.

Progress reports are throttled to about twice per second. Folder-to-GOD now
reports a single `god` stage. Its total includes disc metadata and padding,
just as ISO-to-GOD does; it does not report an intermediate `iso` stage.
The commands and tab-separated progress/result formats are unchanged.
For cancellation, terminate the child process and treat the operation as
failed. An incomplete output may remain; choose a new output path or remove
that known incomplete output before retrying. There is no resume support.

## Data handling

Source files are opened read only. Existing output paths are refused. The
output parent directory must already exist. Output inside the input folder
is refused. Directory links/reparse points, unsafe Windows paths, duplicate
names, cyclic directory trees and out-of-bounds file extents are rejected.
The implementation streams game data rather than loading entire games into
memory. Folder-to-GOD retains directory tables and source-file paths in memory
and streams the planned sectors into the GOD writer using a bounded payload
buffer. Only one source data-file handle is cached at a time; gaps, alignment
and final padding are generated as zeros. There is no ISO-sized scratch file
or whole-game in-memory buffer. Outputs may remain after errors; no input
cleanup is performed.

## Compatibility and limits

- Validated against the supplied Left 4 Dead 2 GOD package and its four DLC
  packages, plus generated fixtures spanning hash and fragment boundaries.
- XDVDFS readers check common partition-only, Xbox, XGD2 and XGD3 offsets.
- GOD reads separate `DataNNNN` fragments. Generated GOD uses the standard
  non-enhanced SVOD layout, with SHA-1 block tables and chained master tables.
- Enhanced-layout reading is implemented but has no real enhanced-layout
  sample validation yet. Single-file SVOD containers are unsupported.
- `verify-god` checks data blocks, hash tables, master chains and metadata hash.
  It does not verify Microsoft digital signatures.
- New GOD metadata is generated from scratch. Packages are unsigned, contain
  no original cover art/signatures, and require a compatible modified console.
  Dashboard recognition and gameplay have **not** been tested on hardware.
- ISO rebuilding preserves file paths and bytes. It does not recreate original
  optical disc security/video partitions, physical layout or retail signatures.
- Folder input supports ASCII Xbox names up to 255 bytes, files smaller than
  4 GiB, and directory tables within the format's 16-bit link range. Reading
  requires valid UTF-8 names safe on Windows; legacy non-UTF-8 names are rejected.
- DLC extraction supports LIVE/PIRS STFS, follows fragmented block chains,
  and checks each extracted data block against its recorded SHA-1. It does not
  authenticate the full STFS hash tree/signature. CON/PEC editing and DLC creation
  are outside this release.
- No FTP, XBE media patching, ISO optimization options, batch UI or GUI is
  supplied. Invoke the CLI repeatedly for batches.
- Only Left 4 Dead 2 and synthetic fixtures were tested; compatibility with
  every game or every feature of the older tools is not claimed.

## Build and tests

Rust 2024 edition, stable Rust with `std`, no downloaded crates:

```text
cargo build --release --locked --offline
cargo test --locked --offline
python tests/validate.py --exe target/release/x360-convert.exe --work NEW_TEST_FOLDER
```

The optional `--game PACKAGE` exercises a real game. The optional
`--exiso PATH` uses an existing Exiso executable only as an external test
oracle. It is not a runtime dependency and is not redistributed.
Tests can create tens of gigabytes of separate outputs for a full game;
all test output goes beneath the explicit new test folder.

`tests/direct.py` compares the streaming output with the previous executable's
explicit folder-to-ISO-to-GOD path, including complete output-file SHA-256
checks and extraction back to the source files. It also checks single-stage
progress and conversion with the old intermediate path deliberately blocked.
Its optional `--game` flag uses existing Left 4 Dead 2 fixtures from the first
validation run; no game content is distributed with the source.

## Redistribution

The newly written converter code is provided under 0BSD (see `LICENSE`),
which has no attribution-retention condition. The compiled executable also
contains Rust standard-library and Windows GNU runtime components. Keep the
bundled `THIRD-PARTY-NOTICES` directory with binary distributions. These
notices are separate from the license on the new converter code. This is
not a legal certification of an attribution-free executable.

See `PROVENANCE.md` for format references and implementation boundaries.
