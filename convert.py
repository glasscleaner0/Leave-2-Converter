"""Command-line entry point for the same pipeline used by the GUI."""
import argparse
import sys
from l4d2_converter.core import Options, convert


def main():
    parser = argparse.ArgumentParser(description='Leave 2 Converter Vanilla v0.5 Public Beta: convert L4D2 addons using your own MakeGameData SDK.')
    parser.add_argument('--input', required=True, help='PC addon VPK or extracted addon root')
    parser.add_argument('--additional-input', dest='additional_inputs', action='append', default=[],
                        help='Another part of the same addon; repeat for multipart campaigns. Conflicting asset bytes are rejected.')
    parser.add_argument('--sdk-bin', required=True, help='Dino D-Day SDK bin folder containing makegamedata.exe')
    parser.add_argument('--output', required=True, help='Build folder; existing builds require --overwrite')
    parser.add_argument('--xbox-game', required=True, help='Clean extracted Xbox game reference folder')
    parser.add_argument('--pc-game', default='', help='PC installation used to resolve missing game dependencies')
    parser.add_argument('--dependency-folder',default='',help='Search this folder recursively for referenced dependencies in VPKs/extracted PC assets')
    parser.add_argument('--dependencies-same-as-input',action='store_true',help='Use the input VPK parent folder, or the extracted input folder, for dependency search')
    parser.add_argument('--runtime-bin', default='', help='Dino D-Day game bin folder, if SDK bin has no runtime DLLs')
    parser.add_argument('--audio-decoder', default='',help='Optional user-owned ffmpeg.exe for unsupported WAV encodings and campaign MP3 adaptation; otherwise checks PATH')
    parser.add_argument('--repair-model-lengths',action='store_true',help='Opt-in validated repair of stale MDL length headers; never reconstructs missing model payload')
    parser.add_argument('--allow-missing-navigation',action='store_true',help='Allow absent NAVs for survival/sandbox maps; still validate existing NAVs. Generate survival metadata only when no mission is supplied.')
    parser.add_argument('--compatibility-repairs',action='store_true',help='Opt-in mission cleanup and documented legacy asset replacements in the private workspace; may change appearance')
    parser.add_argument('--force-supplemented-resources',action='store_true',help='Enable compatibility repairs and reported material/texture fallbacks; never ignore structural or SDK failures')
    parser.add_argument('--diagnostic-source-gaps',action='store_true',help='DIAGNOSTIC ONLY: retain missing animation includes from original input models; marks output incomplete and can crash on hardware')
    parser.add_argument('--retain-hdr-lighting',action='store_true',help='Experimental: retain source HDR or promote standard lighting into the console HDR sections, including ambient lighting')
    parser.add_argument('--leave2-loader',action='store_true',help='Output a ready-to-copy Leave 2 Loader addon folder instead of Install; prefer the embedded image, otherwise use a same-name JPG beside the input VPK')
    parser.add_argument('--xbox-assets', default='', help='Optional extracted console DLC dependencies (assets only)')
    parser.add_argument('--zip-index', type=int, default=9, help='Next consecutive unused zipN.360.zip slot (default 9)')
    parser.add_argument('--reference-map', default='c1m1_hotel', help='Stock string-table dictionary reference')
    parser.add_argument('--resource-list-mode', choices=('per-map', 'on-demand', 'addon-local'), default='per-map', help='Per-map discovered dependencies (default), no lists for an A/B test, or legacy campaign-wide packaged assets')
    parser.add_argument('--timeout', type=int, default=120, help='Maximum seconds per SDK invocation')
    parser.add_argument('--overwrite', action='store_true', help='Reuse a recognized converter output; preserve the previous build in a sibling backup folder')
    args = parser.parse_args()
    try:
        result = convert(Options(**vars(args)), progress=lambda s: print(s, flush=True))
    except Exception as e:
        print('Error:', e, file=sys.stderr)
        return 1
    return 0 if result['status'] == 'converted-awaiting-console-test' else 1


if __name__ == '__main__':
    raise SystemExit(main())
