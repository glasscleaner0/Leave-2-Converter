"""Recover a narrowly verified SDK index tail from the supplied PC companion.

No vertices, strips, animation or collision data are synthesized. This adapter
only applies to a one-model, one-output-LOD triangle-list conversion whose
retained indices and vertex attributes agree with the original first LOD.
"""
import hashlib
import struct
from .formats import unpack_source,pack_source
from .vtx import layout


def _first_lod(data,e):
    u=lambda p:struct.unpack_from(e+'I',data,p)[0]
    def ptr(p,a):
        off=struct.unpack_from(e+'i',data,p)[0];target=a+off
        if not 0<=target<len(data):raise ValueError('Invalid recovery table pointer')
        return target
    if u(28)!=1:raise ValueError('Index recovery requires one body part')
    bp=ptr(32,0)
    if u(bp)!=1:raise ValueError('Index recovery requires one model')
    model=ptr(bp+4,bp);lod=ptr(model+4,model)
    mesh=ptr(lod+4,lod);groups=[]
    if u(lod)>1000:raise ValueError('Too many recovery meshes')
    for m in range(u(lod)):
        mh=mesh+m*9;gh=ptr(mh+4,mh)
        if u(mh)>1000:raise ValueError('Too many recovery strip groups')
        for g in range(u(mh)):
            h=gh+g*33
            if u(h+25):raise ValueError('Topology data cannot be reconstructed')
            sh=ptr(h+20,h)
            strips=[]
            if u(h+16)>1000:raise ValueError('Too many recovery strips')
            for s in range(u(h+16)):
                st=sh+s*35
                if data[st+18]!=1 or u(st+19) or u(st+27):
                    raise ValueError('Index recovery requires triangle lists without bone changes or topology')
                strips.append(tuple(u(st+k) for k in (0,4,8,12)))
            groups.append({'key':(m,g),'header':h,'vertices':u(h),'vertex_offset':ptr(h+4,h),
                'count':u(h+8),'offset':ptr(h+12,h),'strips':strips,'flags':data[h+24]})
    return groups,u(model)


def recover_index_tail(console,source):
    """Return repaired compressed SDK VTX and evidence, or refuse ambiguity."""
    layout(source,'<',33,35)
    plain=console[:36]+unpack_source(console[36:])
    try:
        layout(plain,'>',33,35)
        return console,None
    except (ValueError,struct.error):pass
    src,_=_first_lod(source,'<');dst,lods=_first_lod(plain,'>')
    if lods!=1 or len(src)!=len(dst):raise ValueError('Retained model LOD shape changed')
    replacement=struct.unpack_from('>I',plain,24)[0]
    if replacement+8!=len(plain) or plain[replacement:]!=bytes(8):
        raise ValueError('Index recovery requires an intact empty replacement table at EOF')
    repaired=bytearray(plain);changes=[]
    for a,b in zip(src,dst):
        if any(a[k]!=b[k] for k in ('key','vertices','count','strips','flags')):
            raise ValueError('Source/output geometry metadata differ')
        if not a['count'] or a['count']>1000000:raise ValueError('Invalid recovery index count')
        sv=source[a['vertex_offset']:a['vertex_offset']+a['vertices']*9]
        dv=plain[b['vertex_offset']:b['vertex_offset']+b['vertices']*9]
        if len(sv)!=len(dv) or any(sv[i:i+4]+sv[i+6:i+9]!=dv[i:i+4]+dv[i+6:i+9] for i in range(0,len(sv),9)):
            raise ValueError('Source/output vertex attributes differ')
        raw=source[a['offset']:a['offset']+a['count']*2]
        values=struct.unpack('<'+'H'*a['count'],raw)
        if max(values)>=a['vertices']:raise ValueError('Source index exceeds vertex buffer')
        expected=struct.pack('>'+'H'*a['count'],*values)
        limit=min(b['offset']+len(expected),replacement)
        available=limit-b['offset'];missing=len(expected)-available
        if available<0 or plain[b['offset']:limit]!=expected[:available]:
            raise ValueError('Retained SDK indices differ from source')
        if not missing:continue
        if missing>128 or available*10<len(expected)*9 or available%2:
            raise ValueError('Index loss exceeds bounded tail recovery')
        offset=len(repaired);repaired.extend(expected)
        struct.pack_into('>i',repaired,b['header']+12,offset-b['header'])
        changes.append({'mesh_group':list(b['key']),'index_count':b['count'],'recovered_tail_bytes':missing,
            'retained_prefix_bytes':available,'relocated_buffer_offset':offset,
            'indices_sha256':hashlib.sha256(expected).hexdigest()})
    if not changes:raise ValueError('No verified truncated index tail found')
    layout(repaired,'>',33,35)
    record={'method':'restore_verified_sdk_index_tail_from_source','buffers':changes,
        'all_index_values_from_original_first_lod':True,'vertex_and_strip_payloads_unchanged':True,
        'source_sha256':hashlib.sha256(source).hexdigest(),
        'sdk_sha256':hashlib.sha256(console).hexdigest()}
    return bytes(repaired[:36])+pack_source(bytes(repaired[36:])),record
