"""Discover map/model/material references and resolve against user game files."""
import re
import struct
import posixpath
from pathlib import Path
from .archive import Vpk, XboxZip, safe_name
from .formats import bsp_lump, unpack_source
from .models import model_info,used_material_indices,break_model_references
from .keyvalues import leaf_pairs, decode_text

TEXTURES = {'$basetexture', '$basetexture2', '$bumpmap', '$bumpmap2', '$normalmap',
            '$detail', '$envmap', '$envmapmask', '$selfillummask', '$phongexponenttexture',
            '$blendmodulatetexture', '$dudvmap', '$refracttinttexture', '$flowmap', '$noise_texture',
            '$burndetailtexture', '$woundcutouttexture', '$iris', '$gradienttexture', '$ambientoccltexture', '$corneatexture', '$compress', '$stretch',
            '$phongwarptexture', '$colorwarptexture', '$hdrbasetexture', '$hdrcompressedtexture'}


def canonical(name):
    return safe_name(name).replace('.360.', '.')


def reference_name(name, root=None):
    """Normalize engine-relative references without weakening archive safety."""
    name=name.replace('\\','/').lower()
    if name.startswith('/') or ':' in name: raise ValueError('Unsafe asset reference: ' + name)
    # Some compiled CD-material paths walk out and back into this exact game
    # folder. Resolve only that virtual spelling; never read outside references.
    rebound=posixpath.normpath('left4dead2/'+name)
    if rebound.startswith('left4dead2/'):
        name=rebound.removeprefix('left4dead2/')
    parts=[]
    for part in name.split('/'):
        if part in ('','.'): continue
        if part=='..':
            if not parts: raise ValueError('Asset reference escapes game root: ' + name)
            parts.pop()
        else: parts.append(part)
    result=safe_name('/'.join(parts))
    if root and not result.startswith(root+'/'): raise ValueError('Asset reference escapes '+root+': '+name)
    return result


def pairs(data):
    return leaf_pairs(data)


class References:
    def __init__(self, xbox_root, pc_root=None, supplemental=None, library=None, modded=None):
        self.library=library
        self.dependency_index=library.index if library else {}
        self.xbox_root = Path(xbox_root)
        self.pc_root = Path(pc_root) if pc_root else None
        self.xbox = {}
        self.pc = {}
        self.supplemental = {}
        for folder in ('hl2', 'platform', 'left4dead2'):
            for path in sorted((self.xbox_root / folder).glob('zip*.zip')):
                archive = XboxZip(path)
                for n in archive.entries:
                    self.xbox[canonical(n)] = (archive, n)
        if not self.xbox:
            raise ValueError('Xbox reference folder has no readable stock zip*.zip archives')
        self.modded_report = {}
        if modded:
            from .modded_reference import overlay_install
            self.modded_report = overlay_install(self.xbox, modded)
        if supplemental:
            for path in sorted(Path(supplemental).rglob('*')):
                if path.is_symlink():
                    raise ValueError('Symlinks in Xbox reference assets are unsupported')
                if path.is_file():
                    name = safe_name(path.relative_to(supplemental).as_posix())
                    if name in self.supplemental:
                        raise ValueError('Duplicate supplemental reference path')
                    self.supplemental[name] = path.read_bytes()
        self.supplemental_index = {canonical(n): n for n in self.supplemental}
        if len(self.supplemental_index) != len(self.supplemental):
            raise ValueError('Ambiguous console supplemental paths')
        if self.pc_root:
            for folder in ('hl2', 'left4dead2', 'left4dead2_dlc1', 'left4dead2_dlc2', 'left4dead2_dlc3', 'update'):
                for path in sorted((self.pc_root / folder).glob('*_dir.vpk')):
                    archive = Vpk(path)
                    for n in archive.entries:
                        self.pc[n] = archive

    def pc_read(self, name):
        if name in self.pc:
            return self.pc[name].read(name)
        if self.pc_root:
            for folder in ('update', 'left4dead2_dlc3', 'left4dead2_dlc2', 'left4dead2_dlc1', 'left4dead2', 'hl2'):
                path = self.pc_root / folder / safe_name(name)
                if path.is_file() and not path.is_symlink():
                    return path.read_bytes()
        return self.library.read(name) if self.library else None

    def xbox_read(self, name):
        archive, original = self.xbox[canonical(name)]
        return archive.read(original)


def discover(source, refs, *, include_duplicate_textures=False):
    source = Path(source)
    assets = {safe_name(p.relative_to(source).as_posix()): p.read_bytes()
              for p in source.rglob('*') if p.is_file()}
    resident = dict(assets)
    for n, data in list(assets.items()):
        if n.endswith('.bsp'):
            pak = XboxZip(bsp_lump(data, 40))
            for key in pak.entries:
                if key != '__preload_section.pre':
                    resident[key] = pak.read(key)
    edges = {}
    pending = []
    processed = set()
    added = []
    missing = []
    invalid = []
    adjustments = []
    supplemental_used = set()
    native_reused = set()
    unused_model_materials = []

    def request(name, owner, optional=False, pc_only=False):
        name = reference_name(name)
        edges.setdefault(canonical(owner), set()).add(canonical(name))
        if name.startswith('models/editor/'):
            return None
        if name in resident:
            pending.append((name, resident[name]))
            return resident[name]
        if include_duplicate_textures and name.endswith(('.vmt','.vtf')) and refs.pc_read(name) is not None:
            pc_only=True
        if not pc_only:
            if canonical(name) in refs.xbox:
                native_reused.add(name)
                return b''
            if canonical(name) in refs.supplemental_index:
                actual = refs.supplemental_index[canonical(name)]
                supplemental_used.add(actual)
                data = refs.supplemental[actual]
                pending.append((name, data))
                return data
        data = refs.pc_read(name)
        if data is None:
            if not optional:
                item = {'path': name, 'owner': owner}
                if item not in missing:
                    missing.append(item)
            return None
        resident[name] = assets[name] = data
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        added.append({'path': name, 'owner': owner})
        pending.append((name, data))
        return data

    def material(name, owner):
        name = name.lower().replace('\\', '/')
        if not name.startswith('materials/'):
            name = 'materials/' + name
        if not name.endswith('.vmt'):
            name += '.vmt'
        return request(name, owner)

    has_maps = any(n.endswith('.bsp') for n in assets)
    has_models = any(n.endswith('.mdl') for n in assets)
    has_scripts = any(n.startswith('scripts/') for n in assets)
    for n, data in list(assets.items()):
        # Replacement addons have no BSP to seed dependency traversal.
        # Campaigns can carry unused alternative materials with stale references;
        # start from actual map/model materials instead of every loose VMT.
        stock_material=n.endswith('.vmt') and (canonical(n) in refs.xbox or canonical(n) in refs.supplemental_index)
        independent_material=n.endswith('.vmt') and not n.startswith('materials/models/')
        if n.startswith('scripts/vscripts/') and n.endswith(('.nut','.nuc')):
            pending.append((n,data))
        if n.endswith('.mdl') or (not has_maps and (not has_models or has_scripts or stock_material or independent_material) and n.endswith('.vmt')):
            pending.append((n, data))
        if n.endswith('.bsp'):
            for name in bsp_lump(data, 43).split(b'\0'):
                if name:
                    material(name.decode('cp1252'), n)
            entity = bsp_lump(data, 0)
            for sky in re.findall(rb'"skyname"\s*"([^"\r\n]+)"',entity,re.I):
                for face in ('rt','lf','ft','bk','up','dn'):
                    material('skybox/'+decode_text(sky)+face,n)
            for correction in re.findall(rb'"[^"\r\n]+"\s*"(materials/[^"\r\n]+\.raw)"',entity,re.I):
                request(decode_text(correction),n)
            for value in re.findall(rb'"[^"\r\n]+"\s*"([^"\r\n]*)"', entity):
                reference = value.lower().replace(b'\\', b'/')
                if not (reference.endswith(b'.vmt') or reference.endswith(b'.mdl') and reference.startswith(b'models/')):
                    continue  # Non-path entity text may use arbitrary legacy/UTF-8 bytes.
                text = decode_text(value).lower().replace('\\', '/')
                if reference.endswith(b'.mdl') and reference.startswith(b'models/'):
                    request(text, n)
                elif text.endswith('.vmt'):
                    material(text, n)
            game = bsp_lump(data, 35)
            count = struct.unpack_from('<I', game)[0]
            if count > 1000 or 4 + count * 16 > len(game):
                raise ValueError('Invalid PC game-lump directory')
            for i in range(count):
                ident, flags, _, off, size = struct.unpack_from('<IHHII', game, 4 + i * 16)
                if ident != int.from_bytes(b'sprp', 'big'):
                    continue
                if flags:
                    raise ValueError('Compressed PC static-prop directory is not supported yet')
                props = data[off:off + size]
                models = struct.unpack_from('<I', props)[0]
                if models > 10000 or 4 + models * 128 > len(props):
                    raise ValueError('Invalid static-prop model list')
                for j in range(models):
                    model = props[4 + j * 128:4 + (j + 1) * 128].split(b'\0')[0].decode('cp1252')
                    request(model.lower().replace('\\', '/'), n)
    def script_request(value, owner):
        stem=reference_name('scripts/vscripts/'+value.lower().replace('\\','/'),'scripts')
        if stem.endswith(('.nut','.nuc')):stem=stem[:-4]
        for suffix in ('.nut','.nuc'):
            candidate=stem+suffix
            if (candidate in resident or canonical(candidate) in refs.xbox or
                canonical(candidate) in refs.supplemental_index or refs.pc_read(candidate) is not None):
                request(candidate,owner);return
        request(stem+'.nut',owner)

    def scan_asset(name, data):
        if name.startswith('scripts/vscripts/') and name.endswith(('.nut','.nuc')):
            from .scripts import decode_script, literal_script_includes
            text=decode_script(data) if name.endswith('.nuc') else data
            for include in literal_script_includes(text):script_request(include,name)
        elif name.endswith('.mdl'):
            data = unpack_source(data)
            try:
                info = model_info(data)
            except ValueError as e:
                invalid.append({'path':name,'reason':str(e)})
                return
            endian = info['endian']
            for extension in ('.vvd', '.dx90.vtx', '.phy', '.ani'):
                required = extension in ('.vvd', '.dx90.vtx') and bool(info['meshes'] or info['vertices'])
                if extension == '.ani':
                    continue  # External animation filename is declared by the MDL.
                request(name[:-4] + extension, name, optional=not required, pc_only=endian == '<')
            for include in info['includes']:
                request(include, name)
            for fragment in break_model_references(data):
                request(fragment, name)
            if info['animation_file']:
                request(info['animation_file'], name, pc_only=endian == '<')
            nt, ti, nc, ci = struct.unpack_from(endian + '4I', data, 204)
            if nt > 1000 or nc > 100 or ti + nt * 64 > len(data) or ci + nc * 4 > len(data):
                raise ValueError(f'Invalid model material table: {name}')
            def string(off):
                end = data.find(b'\0', off)
                if not 0 <= off <= end < len(data):
                    raise ValueError('Invalid model string offset')
                return data[off:end].decode('cp1252').lower().replace('\\', '/')
            dirs = [string(struct.unpack_from(endian + 'I', data, ci + 4 * j)[0]) for j in range(nc)] or ['']
            used=used_material_indices(data)
            for j in range(nt):
                offset = ti + 64 * j
                texture = string(offset + struct.unpack_from(endian + 'I', data, offset)[0])
                choices = [reference_name('materials/' + folder + texture + '.vmt','materials') for folder in dirs]
                chosen = next((n for n in choices if n in resident or canonical(n) in refs.xbox
                               or canonical(n) in refs.supplemental_index
                               or n in refs.pc or n in getattr(refs,'dependency_index',{})), choices[0])
                if j not in used and not has_scripts:
                    unused_model_materials.append({'path':chosen,'owner':name,'material_index':j,
                        'reason':'No mesh, eye, bodygroup or skin family uses this material slot'})
                    continue
                request(chosen, name)
            # LOD material replacements are independently reachable even when
            # their names do not occur in the MDL texture table.
            vtx=resident.get(name[:-4]+'.dx90.vtx')
            if vtx and endian=='<':
                if len(vtx)<36:raise ValueError('Truncated VTX material replacement header')
                lods,lists=struct.unpack_from('<2I',vtx,20)
                if lods>64 or lists and lists+lods*8>len(vtx):
                    raise ValueError('Invalid VTX material replacement lists')
                for lod in range(lods if lists else 0):
                    table=lists+lod*8;count,relative=struct.unpack_from('<Ii',vtx,table)
                    start=table+relative
                    if count>1000 or start<0 or start+count*6>len(vtx):
                        raise ValueError('Invalid VTX material replacements')
                    for index in range(count):
                        entry=start+index*6;offset=entry+struct.unpack_from('<i',vtx,entry+2)[0]
                        end=vtx.find(b'\0',offset)
                        if not 0<=offset<=end<len(vtx):raise ValueError('Invalid VTX replacement material name')
                        replacement=vtx[offset:end].decode('cp1252').lower().replace('\\','/')
                        replacement=replacement.removeprefix('materials/').removesuffix('.vmt')
                        # LOD replacement names use the model's CD-material search
                        # directories too. Keep an exact root-relative candidate
                        # for replacement tables that already carry a full path.
                        choices=[reference_name('materials/'+folder+replacement+'.vmt','materials') for folder in dirs]
                        direct=reference_name('materials/'+replacement+'.vmt','materials')
                        if direct not in choices:choices.append(direct)
                        chosen=next((n for n in choices if n in resident or canonical(n) in refs.xbox
                                     or canonical(n) in refs.supplemental_index
                                     or n in refs.pc or n in getattr(refs,'dependency_index',{})),choices[0])
                        request(chosen,name)
        elif name.endswith('.vmt'):
            data = unpack_source(data)
            if data[:1] == b'\xaa':
                raise ValueError(f'Compiled console material needs a plaintext definition: {name}')
            settings = pairs(data)
            has_envmap = any(k == '$envmap' and v.lower() not in ('', '0', 'none') for k, v in settings)
            for key, value in settings:
                if key == 'include':
                    # Patch includes are filesystem filenames relative to the
                    # game root, unlike shader material/texture names.
                    request(value, name)
                elif key == '$fallbackmaterial':
                    material(value, name)
                if key not in TEXTURES:
                    continue
                value = value.lower().replace('\\', '/')
                if value in ('', '0', '1', 'none', 'env_cubemap') or value.startswith('_rt_'):
                    continue
                path = value if value.startswith('materials/') else 'materials/' + value
                if not path.endswith('.vtf'):
                    path += '.vtf'
                path = reference_name(path,'materials')
                if key == '$envmapmask' and not has_envmap and path not in resident and path not in refs.pc and path not in refs.xbox and path not in getattr(refs,'dependency_index',{}):
                    # An absent mask has no effect without an environment-map stage.
                    fixed = re.sub(rb'(?im)^\s*"?\$envmapmask"?\s+[^\r\n]*', b'', data)
                    if fixed == data:
                        request(path, name)
                        continue
                    resident[name] = fixed
                    if name in assets:
                        (source / name).write_bytes(fixed)
                    else:
                        # Embedded VMT repair must be applied to the BSP separately.
                        adjustments.append({'embedded': True, 'path': name, 'data_hex': fixed.hex()})
                    adjustments.append({'path': name, 'reason': 'Removed absent unused envmap mask without envmap'})
                    continue
                request(path, name)
    index = 0
    while index < len(pending):
        name, data = pending[index]
        index += 1
        if name in processed:
            continue
        processed.add(name)
        try:
            scan_asset(name, data)
        except ValueError as e:
            invalid.append({'path':name,'reason':str(e)})
    unused_materials=sorted(n for n in assets if n.endswith('.vmt') and n not in processed)
    # A broken model cannot establish that a material is unused. Keep the
    # previous strict behavior in that case, and preserve all source files.
    if invalid and has_models and not has_maps:
        for name in unused_materials:
            pending.append((name,assets[name]))
        while index<len(pending):
            name,data=pending[index];index+=1
            if name in processed:continue
            processed.add(name)
            try:scan_asset(name,data)
            except ValueError as e:invalid.append({'path':name,'reason':str(e)})
        unused_materials=[]
    return {'reference_edges': {n: sorted(v) for n,v in sorted(edges.items())}, 'added': added, 'missing': missing, 'invalid':invalid, 'adjustments': adjustments,
            'supplemental_used': sorted(supplemental_used), 'native_reused': sorted(native_reused),
            'unused_materials':unused_materials,'unused_model_materials':unused_model_materials}

