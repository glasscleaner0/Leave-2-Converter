# Building

Run the source with Python 3.10+ and Tkinter: `python gui.py`. CLI: `python convert.py --help`. No runtime pip packages are needed by the source application.

For Windows x64 packaging, install build-requirements.txt into a Windows Python environment with Tkinter, then run `python build_release.py`. It uses local source/tool/patch inputs, writes a new dist folder and refuses to overwrite a release. It does not download games, addons or the SDK. Keep the generated EXE, _internal, assets and tools together.

Tests: `python -m unittest discover -s tests`. Optional external-tool fixtures may skip. Hidden startup check: `python gui.py --self-check report.json`, or `Leave 2 Converter Vanilla.exe --self-check report.json`. It creates a hidden GUI and runs x360-convert --help; no game is patched/restored or launched.

BUILD-INFO.json records version/source fingerprint. SHA256SUMS.txt identifies shipped files. Frozen builds can contain tool timestamps and are not claimed bit-for-bit reproducible across environments. The separate source ZIP contains application and bundled-tool source/notices.
