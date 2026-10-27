"""Reusable campaign pipeline. Proprietary conversion runs out of process."""
from dataclasses import dataclass, asdict
from pathlib import Path
import ctypes
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import time
import traceback
from .archive import Vpk, XboxZip, aligned_zip, safe_name
from .dependencies import References, discover, pairs
from .formats import (bsp_lump, sdk_bsp_input, finish_bsp, pack_source,
                      unpack_source, pcm_xwv, validate_asset, static_prop_summary)
from .formats import color_correction
from .scripts import decode_script
from .models import validate_bundle,repair_length_metadata,model_info,model_family
from . import __version__
from .output import prepare_output
from .resources import resource_lists, per_map_graph, MODES
from .embedded import recover_embedded_textures
from .textures import texture_budget
from .inputs import extract_inputs,metadata_input
from .keyvalues import prepare_mission,mission_maps,mission_modes,survival_mission
from .audio import fallback_xwv
from .library import DependencyLibrary,dependency_location
from .hdr import prepare_hdr_input, retain_hdr
from .vtx import prepare_source as prepare_vtx,finish_console as finish_vtx


@dataclass
class Options:
    input: str
    sdk_bin: str
    output: str
    xbox_game: str
    pc_game: str = ''
    runtime_bin: str = ''
    xbox_assets: str = ''
    modded_xbox_game: str = ''
    zip_index: int = 9
    reference_map: str = 'c1m1_hotel'
    timeout: int = 120
    overwrite: bool = False
    resource_list_mode: str = 'per-map'
    additional_inputs: tuple = ()
    audio_decoder: str = ''
    repair_model_lengths: bool = False
    dependency_folder: str = ''
    dependencies_same_as_input: bool = False
    allow_missing_navigation: bool = False
    compatibility_repairs: bool = False
    leave2_loader: bool = False
    retain_hdr_lighting: bool = False
    include_duplicate_textures: bool = False
    force_supplemented_resources: bool = False
    diagnostic_source_gaps: bool = False


def sha(data):
    return hashlib.sha256(data).hexdigest()


def converted_name(name):
    path = Path(name)
    return path.with_suffix('.360' + path.suffix).as_posix()


def texture_alias_reason(name, game):
    try:name.encode('ascii')
    except UnicodeEncodeError:return 'ascii_sdk_texture_path'
    if name.endswith('.pwl.vtf'):
        return 'temporary_vtf_input_alias'
    if len(str(game / converted_name(name))) >= 260:
        return 'short_sdk_texture_path'
    return None


def addon_kind(names):
    return 'campaign' if any(n.endswith('.bsp') or n.startswith('missions/') for n in names) else 'resource-addon'


def package_layout(members, maps, missions):
    """Keep campaign maps and mission registration loose beside the asset ZIP."""
    return dict(members), {**maps, **missions}


def complete_mission_references(rows):
    """Mission-only addons may use maps already verified in the target install."""
    return bool(rows) and all(row['declared'] and
                             set(row['declared']) <= set(row['available']) for row in rows)


def convert_navigation(name, files, game, backend, members, report, allow_missing=False):
    """An explicit opt-in permits absent NAVs, never broken existing NAVs."""
    nav = name[:-4] + '.nav'
    if nav not in files:
        if allow_missing:
            report.setdefault('navigation', []).append({'path':nav, 'status':'absent-allowed'})
            report['warnings'].append(f'{nav}: absent by request; no navigation is generated. Bots/infected may not navigate or spawn correctly.')
        else:
            report['failures'].append({'path':nav, 'reason':'Map has no navigation file; enable Survival map / No navigation file only if intentional'})
        return
    navtarget = converted_name(nav)
    result = backend.run(nav, [navtarget])
    if not result:
        report['failures'].append({'path':nav, 'reason':'NAV conversion failed'})
        return
    from .navigation import transcode
    try:back, details = transcode(unpack_source(result[navtarget]))
    except (ValueError,AssertionError) as e:
        raise ValueError(f'{nav}: Navigation verification failed: {str(e) or type(e).__name__}') from e
    if back != (game / nav).read_bytes():
        raise ValueError('NAV roundtrip differs from PC input')
    members[navtarget] = result[navtarget]
    report.setdefault('navigation', []).append({'path':nav, 'status':'converted', 'roundtrip_exact':True, **details})


class Backend:
    def __init__(self, sdk_bin, runtime_bin, work, timeout, rows):
        sdk_bin = Path(sdk_bin)
        if sdk_bin.is_file():
            sdk_bin = sdk_bin.parent
        if not (sdk_bin / 'makegamedata.exe').is_file():
            raise ValueError('Choose the SDK bin folder containing makegamedata.exe')
        bin_path = work / 'game/bin'
        bin_path.mkdir(parents=True)
        for folder in ([Path(runtime_bin)] if runtime_bin else []) + [sdk_bin]:
            for path in folder.iterdir():
                if path.is_file() and (path.suffix.lower() == '.dll' or path.name.lower() == 'makegamedata.exe'):
                    shutil.copy2(path, bin_path / path.name)
        required = ('tier0.dll', 'vstdlib.dll', 'filesystem_stdio.dll', 'bsppack.dll', 'mdllib.dll', 'vtex_dll.dll', 'vphysics.dll')
        absent = [n for n in required if not (bin_path / n).is_file()]
        if absent:
            raise ValueError('Missing SDK runtime DLLs: ' + ', '.join(absent) + '. Supply the Dino D-Day game bin folder as runtime_bin.')
        self.exe = bin_path / 'makegamedata.exe'
        self.game = work / 'game/left4dead2'
        self.game.mkdir()
        self.logs = work.parent / 'logs'
        self.logs.mkdir()
        self.timeout = timeout
        self.rows = rows
        self.env = dict(os.environ)
        for k in ('VPROJECT', 'VPC_AUTO_ARGS', 'VPC_CONSOLE_ARGS'):
            self.env.pop(k, None)
        self.env['PATH'] = str(bin_path) + os.pathsep + self.env.get('PATH', '')
        self.previous_error_mode = None
        if os.name == 'nt':
            self.previous_error_mode = ctypes.windll.kernel32.SetErrorMode(3)
        self.hash = sha(self.exe.read_bytes())
        try:
            probe = subprocess.run([str(self.exe), '-help'], cwd=self.game, env=self.env,
                                   capture_output=True, timeout=15,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if probe.returncode not in (0, 1) or b'MAKEGAMEDATA' not in probe.stdout.upper():
                raise ValueError(f'MakeGameData startup check failed ({probe.returncode:#x}); verify matching runtime DLLs')
        except Exception:
            self.close()
            raise

    def close(self):
        if self.previous_error_mode is not None:
            ctypes.windll.kernel32.SetErrorMode(self.previous_error_mode)

    def run(self, pattern, expected):
        # Remove only expected scratch outputs: timestamps must never hide failure.
        for name in expected:
            path = self.game / name
            path.unlink(missing_ok=True)
        started = time.monotonic()
        row = {'pattern': pattern, 'expected': expected, 'backend': 'makegamedata'}
        log = b''
        try:
            result = subprocess.run([str(self.exe), pattern, '-f', '-q'], cwd=self.game,
                                    env=self.env, capture_output=True, timeout=self.timeout,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            log = result.stdout + result.stderr
            row['exit'] = result.returncode
            if result.returncode:
                raise ValueError(f'Converter exit {result.returncode:#x}')
            outputs = {}
            for name in expected:
                data = (self.game / name).read_bytes()
                validate_asset(name, data)
                outputs[name] = data
            row['outputs'] = {n: {'bytes': len(b), 'sha256': sha(b)} for n, b in outputs.items()}
            row['success'] = True
        except subprocess.TimeoutExpired as e:
            log = (e.stdout or b'') + (e.stderr or b'')
            row.update(success=False, error='Timed out')
            outputs = {}
        except Exception as e:
            row.update(success=False, error=str(e))
            outputs = {}
        row['seconds'] = round(time.monotonic() - started, 3)
        path = self.logs / f'{len(self.rows):04d}.log'
        path.write_bytes(log)
        row['log'] = path.name
        self.rows.append(row)
        return outputs


def extract_input(path, target):
    return extract_inputs([path],target)


def convert(options, progress=print, cancelled=lambda: False, script_prompt=None, metadata_prompt=None):
    input_path = Path(options.input).resolve()
    if not options.leave2_loader and not 2 <= options.zip_index <= 99:
        raise ValueError('ZIP index must be 2–99')
    if not 1 <= options.timeout <= 3600:
        raise ValueError('Per-asset timeout must be 1–3600 seconds')
    if options.resource_list_mode not in MODES:
        raise ValueError('Resource list mode must be per-map, on-demand or addon-local')
    dependency_root=dependency_location(input_path,options.dependency_folder,options.dependencies_same_as_input)
    if dependency_root:
        dependency_root=dependency_root.resolve()
        target=Path(options.output).resolve()
        if not dependency_root.is_dir():raise ValueError('Dependency location must be an existing folder')
        if target==dependency_root or target in dependency_root.parents:
            raise ValueError('Output cannot replace or contain the dependency folder')
    output, backup = prepare_output(options)
    if backup:
        progress('Previous output saved in: ' + str(backup))
    report = {'version': __version__, 'options': asdict(options), 'status': 'running',
              'hardware_tested': False, 'jobs': [], 'failures': [], 'warnings': [],
              'previous_output_backup': str(backup) if backup else None}
    from .app_paths import source_fingerprint
    report['converter_source_sha256']=source_fingerprint()
    backend = None
    def checkpoint():
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    def check_cancel():
        if cancelled():
            raise InterruptedError('Conversion cancelled; completed diagnostics retained')
    try:
        progress('Preparing a private workspace and extracting the input…')
        from .rust_backend import selected_executable, RustBackend
        rust_exe = selected_executable(options.sdk_bin)
        if rust_exe:
            raise ValueError('Vanilla requires the MakeGameData SDK; use Chocolate for Rust.')
        if rust_exe:
            if options.retain_hdr_lighting:
                raise ValueError('HDR preservation is not enabled for the independent Rust backend')
            backend = RustBackend(rust_exe, output / '.work', options.timeout, report['jobs'], cancelled)
            report['backend'] = {'name':'makegamedata-rs','capabilities':backend.capabilities,'settings':backend.settings}
        else:
            backend = Backend(options.sdk_bin, options.runtime_bin, output / '.work', options.timeout, report['jobs'])
        native_backend = getattr(backend,'native',False) is True
        game = backend.game
        report['backend_sha256'] = backend.hash
        report['input_files'] = extract_inputs([input_path,*options.additional_inputs],game)
        from .addon_info import prepare_addon_info
        report['addon_information']=prepare_addon_info(game,input_path,metadata_prompt,cancelled)
        if report['addon_information']['status']=='manual-info-applied':
            progress('Applied manual addon information to the conversion copy.')
        if options.repair_model_lengths:
            report['model_input_repairs'] = []
            for entry in report['input_files']:
                name=entry['path']
                if not name.endswith('.mdl'): continue
                p=game/name
                original=p.read_bytes()
                if len(original)<80 or original[:4]!=b'IDST' or struct.unpack_from('<I',original,76)[0]==len(original): continue
                family={n:(game/n).read_bytes() for n in (name[:-4]+suffix for suffix in ('.mdl','.vvd','.dx90.vtx','.phy','.ani')) if (game/n).is_file()}
                try:
                    fixed,details=repair_length_metadata(name,family)
                    p.write_bytes(fixed)
                    report['model_input_repairs'].append({**details,'original_sha256':sha(original),'updated_sha256':sha(fixed)})
                except ValueError as e:
                    report['failures'].append({'path':name,'reason':'Model metadata repair refused: '+str(e)})
        report['addon_type'] = addon_kind([n['path'] for n in report['input_files']])
        campaign = report['addon_type'] == 'campaign'
        progress('Detected ' + ('campaign.' if campaign else 'resource replacement addon.'))
        # Never copy addon-provided filesystem configuration into the tool runtime.
        (game / 'gameinfo.txt').write_text('"GameInfo" { "game" "Addon Converter" "SupportsXbox360" "1" '
            '"FileSystem" { "SteamAppId" "870" "SearchPaths" { "Game" "|gameinfo_path|." } } }')
        progress('Indexing the supplied Xbox and PC reference files…')
        library=None
        if dependency_root:
            progress('Scanning the dependency folder (VPKs and extracted assets)…')
            library=DependencyLibrary(dependency_root,excluded=(output,backup),cancelled=cancelled)
            report['dependency_library']=library.summary()
            progress(f'Dependency folder: {library.packages} VPK packages, {len(library.index)} asset paths indexed.')
        refs = References(options.xbox_game, options.pc_game, options.xbox_assets,library=library,modded=options.modded_xbox_game)
        report['modded_console_reference'] = refs.modded_report
        report['mpeg_audio_adapters']=[]
        if campaign and options.audio_decoder:
            from .mpeg_audio import prepare_mpeg_audio
            report['mpeg_audio_adapters']=prepare_mpeg_audio(game,output/'.work/mpeg-audio',options.audio_decoder,options.timeout)
        unknown_mpeg=[row['source'] for row in report['mpeg_audio_adapters'] if row.get('no_direct_references_found')]
        if unknown_mpeg:
            report['warnings'].append(f'{len(unknown_mpeg)} MP3 assets were decoded and retained as WAV without direct static references. Dynamically assembled MP3 paths cannot be inferred or rewritten; see mpeg_audio_adapters for their output names.')
        if report['mpeg_audio_adapters']:
            progress(f"Adapted {len(report['mpeg_audio_adapters'])} MP3 files and their literal references to WAV.")
        if options.compatibility_repairs or options.force_supplemented_resources:
            from .compatibility import apply_repairs
            progress('Applying optional compatibility repairs in the private workspace…')
            report['compatibility_repairs'] = apply_repairs(game, refs)
            report['warnings'].extend(f'Compatibility repair: {row["path"]}: {row.get("reason",row["action"])}' for row in report['compatibility_repairs'])
        dictionary = None
        if campaign:
            baseline_path = Path(options.xbox_game) / f'left4dead2/maps/{options.reference_map}.360.bsp'
            if not baseline_path.exists():
                baseline_path = baseline_path.with_name(options.reference_map + '.bsp')
            baseline = baseline_path.read_bytes()
            baseline_pak = XboxZip(bsp_lump(baseline, 40))
            dictionary = baseline_pak.read('stringtable_dictionary_xbox.dct')
            if not dictionary.endswith(b'\0'):
                raise ValueError('Reference dictionary is not null terminated')
            report['dictionary_sha256'] = sha(dictionary)
        progress('Resolving map, model, and material dependencies…')
        report['dependencies'] = discover(game, refs, include_duplicate_textures=options.include_duplicate_textures)
        if options.compatibility_repairs or options.force_supplemented_resources:
            from .compatibility import recover_internal_material_aliases
            initial=report['dependencies']
            recovered=recover_internal_material_aliases(game,refs,initial['missing'])
            if recovered:
                report.setdefault('compatibility_repairs',[]).extend(recovered)
                report['dependencies']=discover(game,refs,include_duplicate_textures=options.include_duplicate_textures)
                for key in ('added','adjustments','supplemental_used','native_reused'):
                    for item in initial.get(key,[]):
                        if item not in report['dependencies'][key]:report['dependencies'][key].append(item)
                report['warnings'].extend(f'Recovered material alias: {row["path"]}: {row["source"]}' for row in recovered)
        if options.force_supplemented_resources:
            from .compatibility import supplement_missing_materials,supplement_missing_textures
            initial=report['dependencies']
            report['supplemented_resources']=supplement_missing_materials(game,refs,initial['missing'])
            report['supplemented_resources'].extend(supplement_missing_textures(game,refs,initial['missing']))
            if report['supplemented_resources']:
                report['dependencies_before_supplementation']=initial
                report['dependencies']=discover(game,refs,include_duplicate_textures=options.include_duplicate_textures)
                for key in ('added','adjustments','supplemental_used','native_reused'):
                    for item in initial.get(key,[]):
                        if item not in report['dependencies'][key]:report['dependencies'][key].append(item)
                report['warnings'].extend(f'Supplemented resource: {row["path"]}: {row["reason"]}' for row in report['supplemented_resources'])
                progress(f'Supplemented {len(report["supplemented_resources"])} missing materials/textures; rechecked dependencies.')
            (output/'SUPPLEMENTED-RESOURCES.txt').write_text(
                'Forced supplementation enabled. This does not recover original missing assets.\n\n'+
                ('\n'.join(row['path']+'\n  '+row['reason'] for row in report['supplemented_resources']) or
                 'No eligible missing model materials required placeholders.')+'\n',encoding='utf8')
        if options.include_duplicate_textures:
            report['warnings'].append('Duplicate texture/material packaging enabled: available referenced PC assets are included even when found in console references. Native-only assets without a PC source still use the console reference; input assets keep priority.')
        from .script_compatibility import repair_finale_rules
        report['script_compatibility']=repair_finale_rules(game,script_prompt,cancelled)
        for row in report['script_compatibility']:
            message=f"Script compatibility: {row['path']}: {row['action']} SpawnSetRule = SPAWN_FINALE (lines {row['lines']}). {row['reason']}"
            report['warnings'].append(message);progress(message)
        unused=report['dependencies'].get('unused_materials',[])
        if unused:
            report['warnings'].append(f'{len(unused)} loose materials have no discovered map/model references; '
                'their source files are retained and listed in dependencies.unused_materials. '
                'External or dynamic use may still need additional dependencies.')
        if library:
            report['dependency_library']=library.summary()
            report['warnings'].extend('Skipped dependency source '+w['source']+': '+w['reason'] for w in library.warnings)
        required = report['dependencies']['missing']
        if options.diagnostic_source_gaps:
            from .compatibility import retain_source_gaps
            required,gaps=retain_source_gaps(game,{r['path'] for r in report['input_files']},required)
            report['unresolved_source_references']=gaps
            report['warnings'].extend('UNRESOLVED SOURCE REFERENCE: '+r['path']+': '+r['reason'] for r in gaps)
            (output/'UNRESOLVED-SOURCE-REFERENCES.txt').write_text(
                'DIAGNOSTIC BUILD: These original references remain missing. Conversion does not supply them.\n'+
                '\n'.join(r['owner']+' -> '+r['path']+'\n'+r['reason'] for r in gaps)+'\n',encoding='utf8')
        report['failures'].extend(dict(item,reason='Missing required dependency in selected inputs and game references')
                                  for item in required)
        report['failures'].extend(report['dependencies'].get('invalid',[]))
        report['warnings'].append('Dependency scan covers map models and material textures; dynamic script dependencies may require further assets.')
        files = sorted(safe_name(p.relative_to(game).as_posix()) for p in game.rglob('*') if p.is_file())
        members = {'stringtable_dictionary_fallback_xbox.dct': dictionary} if campaign else {}
        supplemental_used = set(report['dependencies']['supplemental_used'])
        included_supplemental = {}
        for name, data in refs.supplemental.items():
            if name.startswith(('maps/', 'missions/', 'resource/ui/')) or name.endswith('.zip'):
                raise ValueError('Supplemental assets must not include maps, missions, menus or archives')
            if not campaign and name not in supplemental_used:
                continue
            if '.360.' in name:
                validate_asset(name, data)
            members[name] = data
            included_supplemental[name] = data
        report['supplemental_assets'] = [{'path': n, 'bytes': len(b), 'sha256': sha(b)}
                                         for n, b in included_supplemental.items()]
        if native_backend:
            try:
                report['native_model_selection'] = backend.preflight(members, report['dependencies'])
            except Exception:
                report['native_model_selection'] = getattr(backend,'selection_report',{'selection_checks_passed':False})
                raise
        maps = {}
        model_members = set()
        models = [n for n in files if n.endswith('.mdl')]
        for index, name in enumerate(models, 1):
            check_cancel()
            progress(f'Model {index}/{len(models)}: {name}')
            family = [n for n in files if n in [name[:-4] + ext for ext in ('.mdl', '.vvd', '.dx90.vtx', '.phy')]]
            try:
                source_info = model_info((game / name).read_bytes())
                declared_animation = source_info['animation_file']
                family = model_family(name, files, source_info)
                model_members.update(family)
                expected = [converted_name(n) for n in family]
                from .models import internal_model_name
                internal,name_adapter=(None,None) if native_backend else internal_model_name(name,(game/name).read_bytes())
                if name_adapter:report.setdefault('model_name_adapters',[]).append(name_adapter)
                input_info = validate_bundle(name, {n: (game / n).read_bytes() for n in family})
                vtx_name=name[:-4]+'.dx90.vtx'
                if vtx_name in family and not native_backend:
                    vtx_data,vtx_record=prepare_vtx((game/vtx_name).read_bytes())
                    (game/vtx_name).write_bytes(vtx_data)
                    report.setdefault('vtx_input_adapters',[]).append({'path':vtx_name,**vtx_record})
            except (ValueError, UnicodeError) as e:
                report['failures'].append({'path': name, 'reason': str(e)})
                checkpoint()
                continue
            animation_result = {}
            alias_animation = not native_backend and declared_animation and declared_animation[:-4] != name[:-4]
            if alias_animation:
                # SDK selects the animation owner by file stem. Temporarily put
                # the actual declaring model there, preserving all original files.
                sdk_owner = game / (declared_animation[:-4] + '.mdl')
                owner_before = sdk_owner.read_bytes() if sdk_owner.exists() else None
                sdk_output = game / converted_name(declared_animation[:-4] + '.mdl')
                output_before = sdk_output.read_bytes() if sdk_output.exists() else None
                sdk_owner.parent.mkdir(parents=True, exist_ok=True)
                try:
                    sdk_owner.write_bytes((game / name).read_bytes())
                    animation_result = backend.run(declared_animation[:-4] + '.*', [converted_name(declared_animation)])
                finally:
                    if owner_before is None: sdk_owner.unlink(missing_ok=True)
                    else: sdk_owner.write_bytes(owner_before)
                    if output_before is None: sdk_output.unlink(missing_ok=True)
                    else: sdk_output.write_bytes(output_before)
                expected = [n for n in expected if n != converted_name(declared_animation)]
                report.setdefault('external_animation_adapters', []).append({'model':name,'animation':declared_animation,
                    'method':'temporary_sdk_owner_stem_alias','source_model_restored':True})
            result = backend.run(name[:-4] + '.*', expected)
            if alias_animation:
                if animation_result: result.update(animation_result)
                else: result = {}
            if result:
                try:
                    target_vtx=converted_name(name[:-4]+'.dx90.vtx')
                    if target_vtx in result and not native_backend:
                        try:
                            result[target_vtx],vtx_record=finish_vtx(result[target_vtx])
                        except ValueError as original_error:
                            from .vtx_recovery import recover_index_tail
                            try:
                                recovered,recovery= recover_index_tail(result[target_vtx],(game/vtx_name).read_bytes())
                                result[target_vtx],vtx_record=finish_vtx(recovered)
                            except (ValueError,struct.error):raise original_error
                            report.setdefault('vtx_index_recoveries',[]).append({'path':target_vtx,**recovery})
                        report.setdefault('vtx_output_adapters',[]).append({'path':target_vtx,**vtx_record})
                    output_info = validate_bundle(converted_name(name), result, console=True)
                    report.setdefault('model_validation', []).append({'path': name, 'input': input_info,
                        'output': output_info, 'companion_checksums_match': True})
                except ValueError as e:
                    report['jobs'][-1].update(success=False, error=str(e))
                    result = {}
            if not result:
                report['failures'].append({'path': name, 'reason': 'Model bundle conversion failed; see job log'})
            for n, data in result.items():
                if n.endswith('.mdl') and not native_backend:
                    plain = unpack_source(data)
                    data = plain[:12] + internal.ljust(64, b'\0') + plain[76:]
                members[n] = pack_source(unpack_source(data)) if not native_backend and n.endswith(('.mdl', '.phy')) else data
            checkpoint()
        textures = [n for n in files if n.endswith('.vtf') and not metadata_input(n)]
        for index, name in enumerate(textures, 1):
            check_cancel()
            if index == 1 or index % 25 == 0 or index == len(textures):
                progress(f'Texture {index}/{len(textures)}')
            result = backend.run(name, [converted_name(name)])
            alias_reason = texture_alias_reason(name, game)
            if not native_backend and not result and alias_reason and report['jobs'][-1].get('exit') == 0:
                # SDK's file enumerator excludes preload helper filenames even
                # when explicitly selected; long paths also fail old SDK writes.
                # Alias a real VTF, then restore its
                # original logical package name; no file contents are patched.
                alias = 'materials/__converter_input/' + sha(name.encode())[:16] + '.vtf'
                alias_path = game / alias
                alias_path.parent.mkdir(parents=True, exist_ok=True)
                alias_path.write_bytes((game / name).read_bytes())
                retry = backend.run(alias, [converted_name(alias)])
                if retry:
                    result = {converted_name(name): retry[converted_name(alias)]}
                    report['jobs'][-2]['resolved_by'] = alias_reason
                    report['jobs'][-1]['original_source'] = name
            if not result and not native_backend:
                from .vtf_adapter import retry_intensity
                failed_job=report['jobs'][-1]
                try:
                    result,adapter=retry_intensity(name,(game/name).read_bytes(),backend)
                    if result:
                        failed_job['resolved_by']=adapter['method']
                        report.setdefault('texture_input_adapters',[]).append(adapter)
                except ValueError as e:
                    failed_job['intensity_adapter_error']=str(e)
            if not result:
                if not native_backend:
                    from .vtf_adapter import retry_legacy_ui
                    failed_job=report['jobs'][-1]
                    try:
                        result,adapter=retry_legacy_ui(name,(game/name).read_bytes(),backend)
                        if result:
                            failed_job['resolved_by']=adapter['method']
                            report.setdefault('texture_input_adapters',[]).append(adapter)
                            report['warnings'].append('Legacy UI SDK mip staging: '+name+'; lower mips generated, original top image retained; SDK output '+str(adapter['output_width'])+'x'+str(adapter['output_height'])+'.')
                    except ValueError as e:
                        failed_job['legacy_ui_adapter_error']=str(e)
            if not result:
                report['failures'].append({'path': name, 'reason': 'Texture conversion failed; see job log'})
            members.update(result)
            if index % 25 == 0:
                checkpoint()
        mapnames = [n for n in files if n.endswith('.bsp')]
        for index, name in enumerate(mapnames, 1):
            check_cancel()
            progress(f'Map {index}/{len(mapnames)}: {name}')
            original = (game / name).read_bytes()
            if not native_backend:
                (game / name).write_bytes(prepare_hdr_input(original) if options.retain_hdr_lighting else sdk_bsp_input(original))
                report.setdefault('bsp_adapters', []).append({'path': name, 'original_sha256': sha(original),
                    'body_unchanged': original[1036:] == (game / name).read_bytes()[1036:]})
            target = converted_name(name)
            result = backend.run(name, [target])
            if result:
                converted_map = result[target]
                if options.retain_hdr_lighting:
                    converted_map, hdr_record = retain_hdr(converted_map, original)
                    report.setdefault('hdr_lighting', []).append({'path': name, **hdr_record})
                if native_backend:
                    from .embedded import missing_embedded_textures
                    if missing_embedded_textures(original, converted_map):
                        raise ValueError('Rust BSP omitted embedded textures; refusing SDK-style recovery')
                    embedded_textures, recovered = {}, []
                else:
                    embedded_textures, recovered = recover_embedded_textures(original, converted_map, backend)
                report.setdefault('embedded_texture_recovery', []).append({'map':name,'restored':recovered})
                if recovered:
                    progress(f'Restored {len(recovered)} SDK-omitted embedded textures for {name}')
                maps[target] = finish_bsp(converted_map, dictionary, extra_members=embedded_textures)
                if native_backend:
                    report.setdefault('native_bsp_packaging',[]).append({'path':name,'rust_sha256':sha(converted_map),
                        'packaged_sha256':sha(maps[target]),'method':'existing_gui_dictionary_and_pak_packaging'})
                # Guard common semantic data against silent conversion damage.
                for lump in (0, 43):
                    if bsp_lump(maps[target], lump) != bsp_lump(original, lump):
                        raise ValueError(f'Map entity/material strings changed: {name}, lump {lump}')
                props = static_prop_summary(original)
                if static_prop_summary(maps[target]) != props:
                    raise ValueError(f'Static-prop inventory changed during conversion: {name}')
                report.setdefault('map_validation', []).append({'path': name,
                    'entity_strings_exact': True, 'material_strings_exact': True,
                    'static_prop_inventory_preserved': True,
                    'static_prop_instances': props['instances'] if props else 0})
                source_pak = XboxZip(bsp_lump(original, 40) or aligned_zip({}))
                console_pak = XboxZip(bsp_lump(maps[target], 40))
                lighting = {n.removesuffix('.vhv') for n in source_pak.entries if n.endswith('.vhv')}
                converted_lighting = {n.replace('.360.', '.').removesuffix('.vhv') for n in console_pak.entries if n.endswith('.vhv')}
                missing_lighting = sorted(lighting - converted_lighting)
                report['map_validation'][-1]['prop_lighting'] = {'source_files':len(lighting),
                    'converted_files':len(converted_lighting), 'missing':missing_lighting}
                if missing_lighting:
                    report['warnings'].append(f'{name}: SDK omitted {len(missing_lighting)} baked prop-lighting files. Geometry converted, but lighting conversion is incomplete; see map_validation and SDK logs.')
                convert_navigation(name, files, game, backend, members, report, options.allow_missing_navigation)
            else:
                report['failures'].append({'path': name, 'reason': 'BSP conversion failed; see job log'})
            checkpoint()
        progress('Preparing scripts, audio, missions, and resource lists…')
        missions = {}
        ignored = []
        for name in files:
            check_cancel()
            p = Path(name)
            if metadata_input(name):
                ignored.append(name)
                continue
            if name in model_members or p.suffix in ('.bsp', '.nav', '.vtf'):
                continue
            data = (game / name).read_bytes()
            if name.startswith('missions/') and p.suffix == '.txt':
                try:mission_id, mission_data = prepare_mission(data)
                except ValueError as e:raise ValueError(f'{name}: {e}') from e
                target = 'missions/' + mission_id.lower() + '.txt'
                if target in missions:
                    raise ValueError('Duplicate mission identifier')
                missions[target] = mission_data
                members[target] = missions[target]
            elif p.suffix == '.nuc':
                target = name[:-4] + '.nut'
                decoded = decode_script(data)
                if target in files and (game / target).read_bytes() != decoded:
                    raise ValueError('Conflicting plaintext and encrypted scripts')
                members[target] = decoded
            elif p.suffix == '.wav':
                target = converted_name(name)
                result = backend.run(name, [target])
                if result:
                    members.update(result)
                else:
                    try:
                        members[target],info=fallback_xwv(game/name,output/'.work/audio',options.audio_decoder,options.timeout)
                        report.setdefault('audio_fallbacks',[]).append({'path':name,**info})
                        report['warnings'].append(f'{name}: SDK audio failed; used {info["method"]} fallback')
                        report['jobs'][-1]['resolved_by'] = info['method']
                    except Exception as e:
                        report['failures'].append({'path':name,'reason':'Audio conversion failed: '+str(e)})
            elif p.suffix in ('.pcf', '.ani'):
                result = backend.run(name, [converted_name(name)])
                if result:
                    members.update(result)
                else:
                    report['failures'].append({'path': name, 'reason': 'Additional binary conversion failed'})
            elif name.startswith('materials/') and p.suffix == '.raw':
                target = converted_name(name)
                result = backend.run(name,[target])
                if result:
                    members.update(result)
                else:
                    try:
                        members[target] = color_correction(data)
                        report['jobs'][-1]['resolved_by'] = 'rgb_lookup_table_passthrough'
                        report.setdefault('color_correction',[]).append({'path':name,'target':target,
                            'palette_bytes_exact':True,'console_visuals_tested':False})
                    except ValueError as e:
                        report['failures'].append({'path':name,'reason':str(e)})
            elif name.startswith('maps/') and name.endswith('_level_sounds.txt'):
                members[name] = data
            elif p.suffix == '.vmt' or (name.startswith(('materials/', 'scripts/', 'sound/', 'resource/')) and p.suffix in ('.nut', '.txt', '.res', '.cfg')):
                members[name] = data
            elif name.startswith('models/') and p.suffix == '.vtx' and (name.removesuffix('.vtx') + '.mdl' in files or name.removesuffix('.xbox.vtx') + '.mdl' in files or name.endswith(('.dx80.vtx', '.sw.vtx'))):
                ignored.append(name)
            elif name.startswith('models/') and p.suffix in ('.vvd', '.phy', '.vtx'):
                report['failures'].append({'path': name, 'reason': 'Orphan/unsupported model companion'})
            else:
                ignored.append(name)
        report['ignored_nonruntime_files'] = ignored
        unsupported = [n for n in ignored if n.startswith(('materials/','sound/','scenes/','resource/','particles/'))
                       and Path(n).suffix in ('.mp3','.raw','.vcd','.vbf','.ttf','.bik','.webm')]
        report['unsupported_runtime_files'] = unsupported
        if unsupported:
            report['failures'].extend({'path':n,'reason':'Runtime asset has no supported console conversion; not silently omitted'} for n in unsupported)
        if maps and not missions and options.allow_missing_navigation:
            stems = sorted(n.removeprefix('maps/').removesuffix('.360.bsp') for n in maps)
            identifier = 'l2csurvival' + sha('\n'.join(stems).encode())[:16]
            _, data = survival_mission(identifier, stems)
            name = 'missions/' + identifier + '.txt'
            missions[name] = members[name] = data
            report['generated_survival_mission'] = name
            report['warnings'].append('No input mission: generated survival-only metadata. This does not add survival entities or a start trigger to a map.')
        report['mission_map_validation'] = []
        for name,data in missions.items():
            declared = mission_maps(data)
            available = []
            for stem in declared:
                target='maps/'+stem+'.360.bsp'
                native = any((Path(options.xbox_game)/'left4dead2'/('maps/'+stem+suffix)).is_file()
                             for suffix in ('.360.bsp','.bsp'))
                if target not in maps and not native and target.replace('.360.', '.') not in refs.xbox:
                    report['failures'].append({'path':target,'owner':name,
                        'reason':'Mission references a missing map; supply the remaining campaign parts'})
                else: available.append(stem)
            report['mission_map_validation'].append({'mission':name,'declared':declared,'available':available,'modes':mission_modes(data)})
        survival_only = bool(missions) and all('survival' in mission_modes(data) and set(mission_modes(data)) <= {'survival','scavenge'} for data in missions.values())
        if survival_only:
            report['addon_type'] = 'survival-addon'
        if campaign and (not missions or not maps and not complete_mission_references(report['mission_map_validation'])):
            report['failures'].append({'reason': 'No converted campaign maps/missions'})
        elif campaign and not maps:
            report['warnings'].append('Mission-only addon: requires the referenced maps to remain installed and enabled in the target Xbox game; no map files are bundled.')
        from .audio_requirements import audit_audio
        report['audio_compatibility'],audio_warnings=audit_audio(members,refs.xbox)
        report['warnings'].extend(audio_warnings)
        (output/'AUDIO-COMPATIBILITY.txt').write_text(report['audio_compatibility']['note']+'\n'+
            '\n'.join(audio_warnings[1:])+'\n',encoding='utf-8')
        list_issues = []
        if options.resource_list_mode == 'per-map' and maps:
            progress('Building map-specific resource lists, including native dependencies…')
            graphs, list_issues = per_map_graph(maps, game, refs, report['dependencies'], members)
            lists = {}
            for name, data in maps.items():
                lists.update(resource_lists({name:data}, members, 'per-map', edges=graphs[name.replace('.360.','.')]))
        else:
            lists = resource_lists(maps, members, options.resource_list_mode, edges={})
        members.update(lists)
        report['resource_lists'] = {'mode':options.resource_list_mode, 'files':sorted(lists),
            'entry_counts':{n:len(data.splitlines()) for n,data in lists.items()},
            'coverage_issues':list_issues, 'runtime_complete':False,
            'entries':{n:[line.strip('"') for line in data.decode('cp1252').splitlines()] for n,data in lists.items()}}
        (output/'RESOURCE-LISTS.txt').write_text(
            'Mode: '+options.resource_list_mode+'\nStatic dependency inventories; hardware behavior is unverified.\n\n'+
            ''.join(name+' ('+str(len(data.splitlines()))+' entries)\n'+data.decode('cp1252')+'\n' for name,data in sorted(lists.items()))+
            'Coverage issues:\n'+('\n'.join(row['map']+': '+row['path']+': '+row['reason'] for row in list_issues) or 'None detected. Dynamic precache coverage is still incomplete.')+'\n',encoding='utf8')
        if lists:
            progress(f'Generated {len(lists)} resource lists; entries per map: '+', '.join(str(len(data.splitlines())) for _,data in sorted(lists.items())))
        if list_issues:
            report['warnings'].append(f'Per-map resource list scan has {len(list_issues)} coverage issues; see resource_lists.coverage_issues. These lists are not exhaustive dynamic precache inventories.')
        if campaign:
            report['warnings'].append('Campaign uses on-demand loading without a borrowed stock-map prefetch list.' if not lists else
                ('Per-map resource lists follow discovered map dependencies, including native assets; dynamic engine/script dependencies can remain unlisted. Console validation is required.' if options.resource_list_mode == 'per-map' else
                 'Optional prefetch lists include packaged render/audio assets for the whole campaign; they are not exact per-map memory budgets.'))
        def stock_texture(name):
            return refs.xbox_read(name) if name.replace('.360.', '.') in refs.xbox else None
        report['texture_budget'], texture_warnings = texture_budget(members, stock_texture, maps)
        report['warnings'].extend(texture_warnings)
        for note in texture_warnings:
            progress('Texture budget: ' + note)
        if not maps and not missions and not members:
            report['failures'].append({'reason': 'No supported runtime assets in this addon'})
        for name, data in members.items():
            if '.360.' in name:
                validate_asset(name, data)
        check_cancel()
        if report['failures']:
            report['status'] = 'failed'
            progress(f'Conversion incomplete: {len(report["failures"])} failures. No {"addon" if options.leave2_loader else "Install"} folder created.')
        else:
            progress('Writing and verifying the Xbox archive…')
            packed, loose = package_layout(members, maps, missions)
            archive = aligned_zip(packed)
            report['packaging'] = {'mode':'split',
                'loose_files':sorted(loose), 'archived_maps':sorted(n for n in packed if n.endswith('.bsp'))}
            if options.leave2_loader:
                from .loader import write_loader_output
                install, loader_report = write_loader_output(output,input_path,game,archive,loose,backend,
                    options.audio_decoder,options.timeout,progress,check_cancel)
                report['leave2_loader']=loader_report
                report['warnings'].extend(loader_report['warnings'])
                report['packaging']['container']='leave2-loader'
                output_base=output
            else:
                install = output / 'Install/left4dead2'
                install.mkdir(parents=True)
                zip_name = f'zip{options.zip_index}.360.zip'
                (install / zip_name).write_bytes(archive)
                for name, data in loose.items():
                    target = install / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                output_base=output/'Install'
            report['outputs'] = [{'path': p.relative_to(output_base).as_posix(),
                                  'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())}
                                 for p in sorted(install.rglob('*')) if p.is_file()]
            report['archive_members'] = [{'path': n, 'bytes': len(b), 'sha256': sha(b)} for n, b in sorted(packed.items())]
            report['status'] = ('diagnostic-with-unresolved-source-references' if report.get('unresolved_source_references') else 'converted-awaiting-console-test')
            if options.leave2_loader:
                from .loader import install_text
                note='DIAGNOSTIC BUILD: unresolved original animation includes remain. See UNRESOLVED-SOURCE-REFERENCES.txt.\n\n' if report.get('unresolved_source_references') else ''
                if report['leave2_loader'].get('requires_l4d1_survivor_support'):
                    from .survivor_requirements import NOTE
                    note+=NOTE+'\n\n'
                (output/'INSTALL.txt').write_text(install_text(report['leave2_loader']['folder'],note),encoding='utf8')
            else:
                (output / 'INSTALL.txt').write_text(
                    ('DIAGNOSTIC BUILD: unresolved original animation includes remain. See UNRESOLVED-SOURCE-REFERENCES.txt.\n\n' if report.get('unresolved_source_references') else '') +
                    f'Converted {report["addon_type"]} candidate: {len(maps)} maps.\n\n'
                    'Use an isolated copy of the project Xbox runtime with its integrated official update,\n'
                    'addon campaign browser, and shared string-table fallback support already installed.\n'
                    'This converter does not patch game executables or install title updates.\n\n'
                    f'Copy Install/left4dead2 into that copy. First verify {zip_name} is unused.\n'
                    'Archive numbers must be consecutive from zip0: a missing earlier slot can prevent\n'
                    'this archive and all later archives from mounting. Use the next consecutive slot,\n'
                    'renaming this output archive if necessary; do not overwrite an installed addon.\n'
                    'Do not overwrite another addon archive or install alongside the old copy of the same addon.\n'
                    'This build includes loose maps/missions plus an asset archive.\n'
                    'Mission/map filenames are retained; stock campaigns are not replaced.\n'
                    + ('Survival addon: the custom Survival browser is not implemented yet.\n'
                       'Test through a survival-capable runtime launcher; metadata alone does not add a menu button.\n' if survival_only else
                       'Use Addon Campaigns in the project browser to select the converted mission.\n' if campaign else
                       'This replacement does not add a campaign menu entry. Test its assets in a stock campaign.\n') +
                    'Keep backup copies of any colliding loose files. To undo, remove only this build\n'
                    'and restore those backups. More than one campaign can coexist if archive slots,\n'
                    'map names, mission IDs, and shared asset paths do not conflict.\n\n'
                    'Output format checks passed; this new conversion still requires console testing.\n'
                    'See report.json for dependencies, warnings, and exact file hashes.\n')
            (output / 'TEXTURE-BUDGET.txt').write_text(
                'Texture sizes are logical mip data, before GPU allocation overhead.\n'
                'This is not a measurement of simultaneous console RAM use.\n\n' +
                ('\n'.join(texture_warnings) if texture_warnings else 'No individual packaged texture exceeds the diagnostic threshold.') + '\n', encoding='utf8')
            progress(f'Finished {report["addon_type"]}: {len(maps)} maps, {len(members)} archive assets. Console test still required.')
    except InterruptedError as e:
        report.update(status='cancelled', error=str(e))
        progress(str(e))
    except Exception as e:
        message=str(e) or type(e).__name__
        report.update(status='failed',error=message,error_type=type(e).__name__)
        (output/'exception.log').write_text(traceback.format_exc(),encoding='utf8')
        progress('Failed: '+message)
    finally:
        if backend:
            backend.close()
        if report.get('unresolved_source_references'):
            progress(f"WARNING: diagnostic build retains {len(report['unresolved_source_references'])} unresolved original animation includes; see UNRESOLVED-SOURCE-REFERENCES.txt.")
        if report.get('supplemented_resources'):
            progress(f"WARNING: {len(report['supplemented_resources'])} material/texture fallbacks change missing source appearance; see SUPPLEMENTED-RESOURCES.txt.")
        checkpoint()
    return report
