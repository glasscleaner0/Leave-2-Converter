"""Stage native dialogue registration for a startup-order diagnostic.

This does not merge scene binaries or convert native audio. Callers supply
archives in actual low-to-high priority order. It is not a general installer.
"""
import hashlib
import struct
from .archive import XboxZip
from .dependencies import canonical
from .dialogue import response_rule_files, validate_scene_image
from .formats import unpack_source
from .keyvalues import leaf_pairs


def startup_dialogue(archives):
    index = {}
    caches = []
    for path in archives:
        archive = XboxZip(path)
        for name in archive.entries:
            index[canonical(name)] = (archive, name)
        name = 'scenes/scenes.360.image'
        if name in archive.entries:
            data = unpack_source(archive.read(name))
            info = validate_scene_image(data)
            if info['endian'] != '>':
                raise ValueError('Expected a native Xbox scene cache: ' + str(path))
            _, _, count, _, offset = struct.unpack_from('>5I', data)
            crcs = {struct.unpack_from('>I', data, offset + i * 16)[0] for i in range(count)}
            caches.append((str(path), data, info, crcs))
    if not caches:
        raise ValueError('No native scene cache found')
    # Keep a complete original cache, including its own string indices. Merely
    # concatenating entries from different caches would invalidate those indices.
    chosen = caches[-1]
    missing = set.union(*(row[3] for row in caches)) - chosen[3]
    if missing:
        raise ValueError('Latest native scene cache omits earlier scenes: ' + str(len(missing)))

    def read(name):
        row = index.get(canonical(name))
        return unpack_source(row[0].read(row[1])) if row else None

    members = response_rule_files('scripts/talker/terror_player.txt', read)
    rule_count = len(members)
    manifest = read('scripts/game_sounds_manifest.txt')
    if manifest is None:
        raise ValueError('Missing native sound manifest')
    members['scripts/game_sounds_manifest.txt'] = manifest
    members['scenes/scenes.360.image'] = chosen[1]
    missing_scripts = []
    waves = set()
    for key, name in leaf_pairs(manifest):
        if key.lower() not in ('preload_file', 'precache_file', 'declare_file'):
            continue
        name = name.lower().replace('\\', '/')
        data = read(name)
        if data is None:
            missing_scripts.append(name)
            continue
        members[name] = data
        for field, value in leaf_pairs(data):
            if field.lower() == 'wave':
                value = value.lstrip('*#@><^)}$!?').replace('\\', '/').lower()
                if value.endswith('.wav'):
                    waves.add('sound/' + value)
    actors = ('/namvet/', '/teengirl/', '/biker/', '/manager/')
    survivor_waves = sorted(n for n in waves if any(actor in n for actor in actors))
    unresolved = [n for n in survivor_waves if canonical(n) not in index]
    origins = {}
    for name, data in members.items():
        row = index.get(canonical(name))
        origins[name] = {'archive': str(row[0].path), 'sha256': hashlib.sha256(data).hexdigest()}
    return members, {
        'kind': 'native-dialogue-startup-diagnostic', 'runtime_tested': False,
        'scene_cache': chosen[2], 'scene_source': chosen[0],
        'all_supplied_scene_crcs_retained': True,
        'response_rule_files': rule_count,
        'declared_l4d1_voice_waves': len(survivor_waves),
        'missing_declared_l4d1_voice_waves': unresolved,
        'missing_manifest_scripts': sorted(set(missing_scripts)),
        'audio_reencoded': False, 'audio_bundled_here': False,
        'requires_existing_native_dlc_audio_mounts': True, 'files': origins,
    }
