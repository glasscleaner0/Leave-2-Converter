# Implementation record

The converter implementation was newly written in Rust for this project.
The supplied utilities were inspected for identifying metadata. Exiso was
executed for help and as an extraction compatibility oracle. The original
God2Iso/Iso2God/Exiso source was not downloaded, decompiled or translated.
None of those utilities or their assets are embedded in the release.

Format information came from public specifications, binary observations of
the user's sample, and search excerpts documenting layout facts:

- Free60 content package / STFS / SVOD field descriptions:
  https://free60.org/System-Software/Formats/STFS/
- Free60 XDVDFS/GDFX descriptor and directory fields:
  https://free60.org/System-Software/Systems/GDFX/
- Free60 XEX execution ID and optional-header fields:
  https://free60.org/System-Software/Formats/XEX/
- Xenia SVOD layout documentation/comments surfaced in search results:
  https://github.com/xenia-project/xenia/blob/master/src/xenia/vfs/devices/stfs_container_device.cc
  Used for layout facts (block/fragment sizes, enhanced-layout offsets),
  not copied implementation code.
- SHA-1 is independently implemented from FIPS PUB 180-4's algorithm:
  https://csrc.nist.gov/pubs/fips/180-4/upd1/final

This was an independent implementation, not a formal separated-team
clean-room process or a legal opinion. Original game content is used only
as local test input, never as a release asset or a generated header template.
