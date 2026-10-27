"""Read model bundle metadata for dependency and consistency checks.

These are independent file-format readers; conversion remains in MakeGameData.
"""
import struct
from .formats import unpack_source


def model_info(data):
    data = unpack_source(data)
    endian = '<' if data[:4] == b'IDST' else '>' if data[:4] == b'TSDI' else None
    if endian is None or len(data) < 360:
        raise ValueError('Unsupported/truncated model header')
    version, checksum = struct.unpack_from(endian + '2I', data, 4)
    if not 44 <= version <= 49 or struct.unpack_from(endian + 'I', data, 76)[0] != len(data):
        raise ValueError('Unsupported model version or declared size')
    def table(offset, stride, limit):
        count, start = struct.unpack_from(endian + '2I', data, offset)
        if count > limit or start + count * stride > len(data):
            raise ValueError('Model table outside file')
        return count, start
    def string(offset):
        end = data.find(b'\0', offset)
        if not 0 <= offset <= end < len(data):
            raise ValueError('Model string outside file')
        return data[offset:end].decode('cp1252').lower().replace('\\', '/')
    count, start = table(232, 16, 1000)
    meshes = vertices = 0
    for i in range(count):
        body = start + i * 16
        n = struct.unpack_from(endian + 'I', data, body + 4)[0]
        relative = struct.unpack_from(endian + 'I', data, body + 12)[0]
        model = body + relative
        if n > 10000 or model + n * 148 > len(data):
            raise ValueError('Model body outside file')
        for j in range(n):
            position = model + j * 148
            meshes += struct.unpack_from(endian + 'I', data, position + 72)[0]
            vertices += struct.unpack_from(endian + 'I', data, position + 80)[0]
    count, start = table(336, 8, 1000)
    includes = [string(start + i * 8 + struct.unpack_from(endian + 'I', data, start + i * 8 + 4)[0]) for i in range(count)]
    animation_name = struct.unpack_from(endian + 'I', data, 348)[0]
    animation_blocks = struct.unpack_from(endian + 'I', data, 352)[0]
    return {'version': version, 'checksum': checksum, 'meshes': meshes, 'vertices': vertices,
            'bones': struct.unpack_from(endian + 'I', data, 156)[0], 'includes': includes,
            'animation_file': string(animation_name) if animation_name and animation_blocks > 1 else None,
            'endian': endian}


def used_material_indices(data):
    """Find material-table entries reachable by any bodygroup or skin family.

    Eyes name a material directly; mesh material numbers index the skin table.
    Nothing in the model is rewritten or removed.
    """
    info=model_info(data);data=unpack_source(data);endian=info['endian']
    def u(offset):return struct.unpack_from(endian+'I',data,offset)[0]
    def bounds(offset,count,stride):
        if count>1000000 or offset<0 or offset+count*stride>len(data):
            raise ValueError('Model material-use table outside file')
    nt=u(204);skin_slots=u(220);families=u(224);skin_start=u(228)
    if nt>1000:raise ValueError('Invalid model material count')
    if not nt:return set()
    bounds(skin_start,skin_slots*families,2)
    slots=set();direct=set();bounds(u(236),u(232),16)
    for b in range(u(232)):
        body=u(236)+b*16;start=body+u(body+12);bounds(start,u(body+4),148)
        for m in range(u(body+4)):
            model=start+m*148;mesh_start=model+u(model+76);bounds(mesh_start,u(model+72),116)
            for j in range(u(model+72)):slots.add(u(mesh_start+j*116))
            eye_start=model+u(model+104);bounds(eye_start,u(model+100),172)
            for j in range(u(model+100)):direct.add(u(eye_start+j*172+52))
    used=set(direct)
    for slot in slots:
        if families and skin_slots:
            if slot>=skin_slots:raise ValueError('Mesh material outside skin table')
            for family in range(families):
                used.add(struct.unpack_from(endian+'H',data,skin_start+2*(family*skin_slots+slot))[0])
        else:used.add(slot)
    if any(index>=nt for index in used):raise ValueError('Used material outside model texture table')
    return used


def validate_bundle(model, members, console=False):
    info = model_info(members[model])
    stem = model.removesuffix('.360.mdl') if console else model.removesuffix('.mdl')
    required = (('.360.vvd', '.dx90.360.vtx') if console else ('.vvd', '.dx90.vtx')) if info['meshes'] or info['vertices'] else ()
    for suffix in required:
        name = stem + suffix
        if name not in members:
            raise ValueError(f'Missing geometry companion: {name}')
    for suffix, offset, magic in (('.360.vvd' if console else '.vvd', 8, b'VSDI' if console else b'IDSV'),
                                  ('.dx90.360.vtx' if console else '.dx90.vtx', 16, None)):
        name = stem + suffix
        if name not in members:
            continue
        data = unpack_source(members[name])
        if len(data) < offset + 4 or (magic and data[:4] != magic):
            raise ValueError(f'Invalid model companion: {name}')
        checksum = struct.unpack_from(info['endian'] + 'I', data, offset)[0]
        if checksum != info['checksum']:
            raise ValueError(f'Model companion checksum mismatch: {name}')
    return info


def repair_length_metadata(model,members):
    """Opt-in repair of a small stale length field; all payload bytes retained."""
    original=members[model]
    if len(original)<360 or original[:4]!=b'IDST': raise ValueError('Expected a PC model header')
    declared=struct.unpack_from('<I',original,76)[0]
    if declared==len(original): return original,None
    if declared<360 or abs(declared-len(original))>4096:
        raise ValueError('Model length difference is too large for metadata repair')
    fixed=bytearray(original);struct.pack_into('<I',fixed,76,len(fixed));fixed=bytes(fixed)
    validate_bundle(model,{**members,model:fixed})
    nt,ti,nc,ci=struct.unpack_from('<4I',fixed,204)
    if nt>1000 or nc>100 or ti+nt*64>len(fixed) or ci+nc*4>len(fixed):
        raise ValueError('Model material table is truncated; cannot repair metadata')
    offsets=[struct.unpack_from('<I',fixed,ci+4*i)[0] for i in range(nc)]
    offsets += [ti+64*i+struct.unpack_from('<I',fixed,ti+64*i)[0] for i in range(nt)]
    if any(not 0<=off<len(fixed) or fixed.find(b'\0',off)<0 for off in offsets):
        raise ValueError('Model material string is truncated; cannot repair metadata')
    if original[:76]+original[80:]!=fixed[:76]+fixed[80:]: raise ValueError('Model repair changed payload')
    return fixed,{'path':model,'declared_bytes':declared,'actual_bytes':len(original),
                  'payload_bytes_unchanged':True,'method':'validated_length_metadata',
                  'note':'Does not reconstruct missing data or establish console compatibility.'}


def model_family(name, files, info):
    """ANI ownership comes from the model declaration, never its filename alone."""
    names=set(files)
    family=[name[:-4]+extension for extension in ('.mdl','.vvd','.dx90.vtx','.phy')
            if name[:-4]+extension in names]
    animation=info.get('animation_file')
    if animation and animation in names:
        family.append(animation)
    return family


def internal_model_name(name,data):
    """Preserve a valid source header name when an archive path exceeds its slot."""
    requested=name.removeprefix('models/').encode('ascii')
    if len(requested)<64:return requested,None
    data=unpack_source(data)
    if len(data)<80 or data[:4]!=b'IDST':raise ValueError('Expected PC model for internal name preservation')
    field=data[12:76];end=field.find(b'\0')
    if not 0<end<64:raise ValueError('Long model path has no valid source internal name')
    original=field[:end]
    from .archive import safe_name
    safe_name(original.decode('ascii'))
    return original,{'path':name,'method':'preserve_original_internal_model_name',
        'internal_name':original.decode('ascii'),'archive_path_unchanged':True}


def break_model_references(data):
    """Read named break fragments from a studio model's embedded KeyValues."""
    from .keyvalues import leaf_pairs
    data=unpack_source(data)
    if len(data)<320 or data[:4] not in (b'IDST',b'TSDI'):raise ValueError('Invalid model break-data header')
    endian='<' if data[:4]==b'IDST' else '>'
    start,size=struct.unpack_from(endian+'2I',data,312)
    if not size:return []
    if start<320 or start+size>len(data):raise ValueError('Model break KeyValues outside file')
    result=[]
    for key,value in leaf_pairs(data[start:start+size].rstrip(b'\0')):
        if key!='model':continue
        value=value.lower().replace('\\','/')
        if not value.startswith('models/'):value='models/'+value
        if not value.endswith('.mdl'):value+='.mdl'
        if any(p in ('','..','.') for p in value.split('/')) or ':' in value:raise ValueError('Unsafe break model reference')
        if value not in result:result.append(value)
    return result


def rebind_material_names(data, names):
    """Append isolated material names without moving geometry or animation data.

    Works on validated PC/console studio headers. Companion-file checksum and
    all existing payload bytes remain unchanged except header/string offsets.
    Returned bytes are uncompressed; callers decide how to store the result.
    """
    from .archive import safe_name
    data=unpack_source(data);info=model_info(data);endian=info['endian']
    count,start=struct.unpack_from(endian+'2I',data,204)
    if count>1000 or start+count*64>len(data) or len(names)!=count:
        raise ValueError('Material aliases must match the bounded texture table')
    names=[safe_name(name) for name in names]
    if any(name.endswith(('.vmt','.vtf')) or not name.isascii() for name in names):
        raise ValueError('Studio material aliases need ASCII names without extensions')
    out=bytearray(data);changes=[]
    for i,name in enumerate(names):
        entry=start+64*i;old=entry+struct.unpack_from(endian+'I',data,entry)[0]
        if not 0<=old<len(data) or data.find(b'\0',old)<0:raise ValueError('Unbounded original material string')
        position=len(out);out.extend(name.encode('ascii')+b'\0')
        struct.pack_into(endian+'I',out,entry,position-entry);changes.append([entry,entry+4])
    # Replace CD-material search paths with a single empty root for exact names.
    out.extend(bytes((-len(out))%4));table=len(out);out.extend(struct.pack(endian+'I',table+4));out.append(0)
    struct.pack_into(endian+'2I',out,212,1,table)
    struct.pack_into(endian+'I',out,76,len(out));changes.extend([[76,80],[212,220]])
    allowed={i for a,b in changes for i in range(a,b)}
    if any(a!=b and i not in allowed for i,(a,b) in enumerate(zip(data,out))):
        raise ValueError('Unexpected original payload mutation')
    after=model_info(bytes(out))
    if after!=info:raise ValueError('Model structure or companion checksum changed')
    return bytes(out),{'material_count':count,'original_bytes':len(data),'output_bytes':len(out),
        'checksum':info['checksum'],'geometry_and_animation_offsets_preserved':True,'changed_original_ranges':changes}
