"""Map-scoped prefetch inventories; these are not complete runtime residency graphs."""
import re
import struct
from pathlib import Path
from .archive import XboxZip
from .dependencies import canonical, reference_name, TEXTURES, pairs
from .formats import bsp_lump, unpack_source
from .models import model_info, used_material_indices
from .keyvalues import decode_text

MODES = ('per-map', 'on-demand', 'addon-local')
PREFETCH_EXTENSIONS = ('.bsp', '.mdl', '.vmt', '.vtf', '.wav')


def resource_lists(maps, members, mode='on-demand', *, edges=None):
    if mode not in MODES:
        raise ValueError('Resource list mode must be per-map, on-demand or addon-local')
    if mode == 'on-demand':
        return {}
    if mode == 'per-map' and edges is None:
        raise ValueError('Per-map lists require a discovered dependency graph')
    local = {canonical(n) for n in members if n.startswith(('materials/', 'models/', 'sound/'))
             and canonical(n).endswith(PREFETCH_EXTENSIONS[1:])}
    output = {}
    for name in sorted(maps):
        root = canonical(name)
        reachable = {root}
        pending = [root]
        while pending and mode == 'per-map':
            for child in edges.get(pending.pop(), ()):
                child = canonical(child)
                if child not in reachable:
                    reachable.add(child)
                    pending.append(child)
        selected = reachable if mode == 'per-map' else local | {root}
        selected = {n for n in selected if n == root or
                    n.startswith(('materials/', 'models/', 'sound/')) and n.endswith(PREFETCH_EXTENSIONS[1:])}
        # Logical filenames match the Xbox loader's stock lists; .360 is resolved by the engine.
        lines = ['"' + n.replace('/', chr(92)) + '"' for n in sorted(selected)]
        output['reslists_xbox/' + Path(root).stem + '.360.lst'] = ('\n'.join(lines) + '\n').encode('cp1252')
    return output


def per_map_graph(maps, source, refs, discovery, members=None):
    """Extend conversion edges through stock resources, without copying or editing them.

    Start from map-owned edges only. Read plaintext PC VMTs for native material
    dependencies when available; inspect actual console MDLs for native model
    tables. Dynamic engine/script precaches remain a documented coverage limit.
    """
    source = Path(source)
    graph = {canonical(n): set(canonical(v) for v in values)
             for n, values in discovery.get('reference_edges', {}).items()}
    issues = []
    available = {canonical(n) for n in (members or {})} | {canonical(n) for n in maps}
    cache = {}
    excluded = {canonical(row['path']) for row in discovery.get('missing', [])}
    excluded.update(canonical(row['path']) for row in discovery.get('optional_animation_slots', []))
    embedded = {}
    map_sources = {}
    for name in maps:
        root = canonical(name)
        data = (source / root).read_bytes()
        map_sources[root] = data
        pak = XboxZip(bsp_lump(data, 40))
        embedded[root] = {canonical(n): pak.read(n) for n in pak.entries if n != '__preload_section.pre'}

    def read(name, root):
        if name in embedded[root]: return embedded[root][name]
        if name in cache: return cache[name]
        payload = read_base(name)
        cache[name] = payload
        return payload

    def read_base(name):
        path = source / name
        if path.is_file(): return path.read_bytes()
        if name.endswith('.mdl') and name in refs.xbox: return refs.xbox_read(name)
        if name in refs.supplemental_index:
            return refs.supplemental[refs.supplemental_index[name]]
        pc = refs.pc_read(name)
        if pc is not None: return pc
        if name in refs.xbox: return refs.xbox_read(name)
        return None

    def material(value):
        value = value.lower().replace(chr(92), '/')
        if value.endswith('.spr'): value = value[:-4]
        if not value.startswith('materials/'): value = 'materials/' + value
        if not value.endswith('.vmt'): value += '.vmt'
        return reference_name(value, 'materials')

    def literals(data):
        # Explicit file paths in entities/scripts. Named sound events and paths
        # assembled at runtime cannot be inferred from this static scan.
        for value in re.findall(rb'"([^"\r\n]*)"', data):
            text = decode_text(value).lower().replace(chr(92), '/')
            text = text.lstrip('*#@<>^)}!?')
            if text.startswith(('models/', 'materials/', 'sound/', 'scripts/')) and text.endswith(('.mdl','.vmt','.vtf','.wav','.nut')):
                yield reference_name(text)
            elif text.endswith('.wav') and '/' in text:
                yield reference_name('sound/' + text)

    result = {}
    for root, data in map_sources.items():
        # A separate graph per map prevents equal embedded filenames from
        # leaking dependencies from a different map's embedded material.
        active = {n: set(v) for n,v in graph.items()}
        active.setdefault(root, set()).update(literals(bsp_lump(data, 0)))
        for key,value in pairs(bsp_lump(data, 0)):
            if key == 'vscripts':
                active[root].update(reference_name('scripts/vscripts/' + n + ('' if n.endswith('.nut') else '.nut')) for n in value.split())
            elif key in ('material','texture') and value and not value.startswith('*') and not value.isdecimal():
                active[root].add(material(value))
        pending = [root]
        visited = set()
        while pending:
            name = pending.pop()
            if name in visited or name in excluded or name.startswith('models/editor/'): continue
            visited.add(name)
            children = active.setdefault(name, set())
            if name in embedded[root]: children.clear()
            try:
                # Existing edges already came from the validated source parser.
                # Native leaves and scripts need extra read-only traversal.
                if name != root and (name not in graph or name in embedded[root] or name.endswith('.nut')) and name.endswith(('.mdl','.vmt','.nut')):
                    payload = read(name, root)
                    if payload is None:
                        issues.append({'map':root,'path':name,'reason':'Dependency definition unavailable for deeper traversal'})
                    elif name.endswith('.nut'):
                        children.update(literals(payload))
                    elif name.endswith('.vmt'):
                        payload = unpack_source(payload)
                        if payload[:1] == b'\xaa':
                            issues.append({'map':root,'path':name,'reason':'Compiled native material has no plaintext definition available'})
                        else:
                            for key,value in pairs(payload):
                                if key == 'include': children.add(material(value))
                                elif key in TEXTURES and value.lower() not in ('','0','1','none','env_cubemap') and not value.lower().startswith('_rt_'):
                                    value = value.lower().replace(chr(92), '/')
                                    child = value if value.startswith('materials/') else 'materials/' + value
                                    children.add(reference_name(child if child.endswith('.vtf') else child + '.vtf','materials'))
                    else:
                        payload = unpack_source(payload)
                        info = model_info(payload); endian = info['endian']
                        children.update(canonical(n) for n in info['includes'])
                        nt,ti,nc,ci = struct.unpack_from(endian+'4I',payload,204)
                        if nt > 1000 or nc > 100 or ti+nt*64 > len(payload) or ci+nc*4 > len(payload):
                            raise ValueError('Invalid native model material table')
                        def string(off):
                            end = payload.find(b'\0',off)
                            if not 0 <= off <= end < len(payload): raise ValueError('Invalid native model material string')
                            return payload[off:end].decode('cp1252').lower().replace(chr(92),'/')
                        dirs = [string(struct.unpack_from(endian+'I',payload,ci+4*j)[0]) for j in range(nc)] or ['']
                        for j in used_material_indices(payload):
                            if j >= nt: raise ValueError('Invalid native model material index')
                            pos = ti+64*j
                            texture = string(pos+struct.unpack_from(endian+'I',payload,pos)[0])
                            choices = [reference_name('materials/'+folder+texture+'.vmt','materials') for folder in dirs]
                            chosen = next((n for n in choices if n in embedded[root] or (source/n).is_file() or n in refs.xbox or n in refs.pc or n in refs.supplemental_index), choices[0])
                            children.add(chosen)
                children.difference_update(excluded)
                pending.extend(children - visited)
            except (ValueError,struct.error,UnicodeError) as error:
                issues.append({'map':root,'path':name,'reason':str(error)})
        absent = {n for n in visited if n.endswith(PREFETCH_EXTENSIONS) and n not in available and n not in embedded[root] and n not in refs.xbox}
        for name in sorted(absent):
            issues.append({'map':root,'path':name,'reason':'No known installed console asset; omitted from prefetch list'})
        result[root] = {n:sorted(active[n] - absent - excluded) for n in visited}

    return result, issues
