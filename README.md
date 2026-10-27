# Leave 2 Converter Vanilla v0.5 Public Beta

Convert Left 4 Dead 2 PC addons for Xbox 360 and prepare an extracted game with Leave 2 Loader.

## Launch

**Windows portable:** extract the entire ZIP into a writable folder, then open **Leave 2 Converter Vanilla.exe**. Keep `_internal`, `assets` and `tools` beside it. No Python installation is needed.

**Source release:** install Python 3.10 or newer with Tkinter, extract the entire ZIP, then open **Start-Converter.cmd** or run `python gui.py`. The source application needs no pip packages.

Settings are saved beside the application. Move the whole folder when relocating it; do not run inside a ZIP or a protected system folder. Appearance defaults to the Windows theme, with Light and Dark options.

## Requirements

- Your extracted Xbox 360 L4D2 game containing `default.xex`. Loader currently supports the `.360.zip` naming layout only.
- For addon conversion: your own Dino D-Day SDK `bin` containing `makegamedata.exe` and matching DLLs. Supply the Dino D-Day game `bin` as the runtime location if required DLLs are missing. These tools are not bundled.
- A PC addon VPK or extracted addon folder. Additional parts of one addon can be combined.
- Optional PC game files and dependency folders to resolve referenced assets.
- Optional, recommended FFmpeg for image/audio decoding; select your own `ffmpeg.exe`.
- A modified Xbox capable of running the patched game. Xenia success does not establish hardware compatibility.

## Quick start

1. Back up the game. On **Loader Patch**, select the folder containing `default.xex`, choose **Check game**, then **Patch Me Up!!**.
2. Disable Aurora's separate L4D2 title update for this copy; the patch integrates its matching update.
3. On **Converter**, select the addon, SDK/runtime folders, Xbox reference and a separate output folder. Enable **Leave 2 Loader output**.
4. Missing addon details trigger an optional editor: required name, optional description/author. Original inputs stay unchanged.
5. Copy the named addon folder directly into the game's `left4dead2/addons`. Keep its ZIP, maps, missions and UI folder together.
6. Start that same game copy, open ADD-ONS / Leave 2 Loader, enable the addon and restart. Choose the appropriate mode's Addon campaigns screen.

See **INSTALLATION.md** or the Installation instructions link beside Open output for examples.

## Pages

- **Converter:** campaigns/resource replacements, dependency search, compatibility repairs, explicitly reported supplementation, duplicate textures and manual metadata.
- **Loader Patch:** supported-file checks, verified backups and destructive clean rollback with mandatory acknowledgement.
- **Offline DLC:** native Xbox DLC packaging, L4D1 survivor support and startup audio registration from your own packages. Optional PC thumbnail recovery uses saved Converter PC/SDK locations and preserves the native 256x128 DXT1 profile/top mip.
- **Xbox game files:** independent x360-convert 0.2.0 for extracted files, ISO/GOD containers and DLC extraction.

Unfinished PC-to-DLC conversion, HDR UI controls, xdReanims-specific switches, single-ZIP campaign output and the failed Float Survival experiment are not exposed in the public GUI.

## Restore clean game

The confirm button stays disabled until you acknowledge permanent deletion of installed converted mods. Restore reverses all saved Loader patch-backup layers and removes installed addons, choices, extra numbered ZIPs such as zip5, and managed startup registration. Stock zip0/zip1 and an official update archive present before Loader are protected. Original-file backups remain; converted outputs outside the game folder are untouched. Damaged backups or changed patch targets can block restoration. Files never backed up cannot be reconstructed.

Close the game/Xenia before installation or restoration. Keep an independent game backup.

## Beta limits and controls

Converted successfully means conversion checks passed, not guaranteed console compatibility. Larger maps can exceed memory limits; newer scripts, model/animation, particle and framework features are not automatically backported. Repairs/substitutions may alter appearance or behavior and are reported. An intermittent main-menu breakpoint remains under investigation.

User-confirmed hardware controls include offline No Mercy, Death Toll, Cold Stream, Crash Course, Loader restart and rotary materials in Tumtara/No Mercy Rooftop. A fresh Minty install and clean rollback were user-confirmed. This does not certify every addon or game revision. Native mission definitions determine mode availability; missing PC Survival arenas are not added.

## Bug reports

Provide version, addon ID/name, report.json, relevant logs, options, launched game folder and platform (Xenia/hardware). Distinguish conversion errors from runtime failures. Review reports for personal paths before posting; do not attach SDK binaries, game files or paid addon content.

## Licenses

Original Python source: **GNU GPL version 3**, matching the project's chosen license; see LICENSE and NOTICE.md. x360-convert remains **0BSD** with its own source/notices. Windows runtime notices are included. MakeGameData/SDK DLLs, FFmpeg, game installations, DLC packages, Workshop addons and personal settings are not bundled. Loader game patch data is described separately in NOTICE.md; GPL does not relicense third-party game material.
