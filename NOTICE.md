# Source, patch data and third-party components

Original Python application: Copyright (C) 2026 Leave 2 Converter contributors. GNU GPL version 3; see LICENSE. This program comes without warranty. This license does not change third-party tool, artwork or game-content licenses.

MakeGameData and optional FFmpeg run as external processes. SDK executable/DLL files are temporarily copied from the user's installation into a private conversion workspace; these copies are excluded from the release. No SDK implementation code, SDK headers, MakeGameData/SDK binaries or FFmpeg binaries are bundled.

The Loader bundle includes hash-locked executable deltas and generated resource-archive payloads for the supported game/update and menu patches. Resource payloads include some Valve-authored menu/update material. This is game patch data, not original GPL Python code or a claim that game assets are GPL-licensed. Supported source game files are required for executable reconstruction. Complete game executables, DLC campaigns, survivor packages and Workshop addons are not shipped. Offline DLC and PC preview images are generated locally from the user's files.

The format readers/writers and orchestration are project code. Thin-ICE attributes algorithm/constants to Matthew Kwan's public-domain ICE reference. NAV verification was cross-checked against KitRifty/sourcepawn-navmesh. These are format/algorithm references, not bundled proprietary SDK implementation code.

x360-convert 0.2.0 retains its 0BSD license, source and THIRD-PARTY-NOTICES under tools/x360-convert. Preserve its Rust/compiler and MinGW-w64 runtime notices. No God2Iso, Iso2God or Exiso binaries or implementation code are included.

The Windows application bundles Python 3.12 and Tcl/Tk. Their licenses and PyInstaller's distribution notice/bootloader exception are included under THIRD-PARTY-NOTICES. Build tools themselves are not application runtime dependencies. See BUILDING.md and BUILD-INFO.json.

Vanilla/medkit artwork was supplied for this project by the project owner. This is an unofficial community tool; Valve's names, marks and third-party material remain their owners' property.
