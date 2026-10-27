"""Independent VTX v7 layout adaptation around the user-owned SDK.

L4D2 legacy strip-group/strip headers are 25/27 bytes; the supplied
MakeGameData processes 33/35-byte headers. Geometry buffers are never rebuilt.
"""
import struct
import hashlib
from .formats import unpack_source,pack_source


def layout(data,endian,group_size,strip_size,require_zero=True):
    if len(data)<36 or struct.unpack_from(endian+'I',data)[0]!=7:
        raise ValueError('Unsupported VTX header/version')
    def u(p):return struct.unpack_from(endian+'I',data,p)[0]
    def bound(p,n,stride):
        if n>1000000 or p<0 or p+n*stride>len(data):raise ValueError('VTX table/buffer outside file')
    pointers=[];headers=[];buffers=[]
    def pointer(field,anchor):
        value=struct.unpack_from(endian+'i',data,field)[0];target=anchor+value
        if not 0<=target<=len(data):raise ValueError('VTX relative pointer outside file')
        if value:pointers.append((field,anchor,target))
        return target
    def buffer(start,count,stride):
        bound(start,count,stride);buffers.append((start,count*stride,data[start:start+count*stride]))
    pointer(32,0);pointer(24,0)
    if u(20)>64:raise ValueError('Invalid VTX LOD count')
    if u(24):
        for i in range(u(20)):
            h=u(24)+i*8;bound(h,1,8);start=pointer(h+4,h);bound(start,u(h),6)
            for j in range(u(h)):
                replacement=start+j*6;name=pointer(replacement+2,replacement)
                end=data.find(b'\0',name)
                if end<name:raise ValueError('Unterminated VTX material name')
                buffers.append((name,end-name+1,data[name:end+1]))
    bound(u(32),u(28),8);counts={'models':0,'lods':0,'groups':0,'strips':0}
    for i in range(u(28)):
        bp=u(32)+i*8;start=pointer(bp+4,bp);bound(start,u(bp),8)
        for j in range(u(bp)):
            model=start+j*8;lod_start=pointer(model+4,model);bound(lod_start,u(model),12);counts['models']+=1
            for l in range(u(model)):
                lod=lod_start+l*12;mesh_start=pointer(lod+4,lod);bound(mesh_start,u(lod),9);counts['lods']+=1
                for n in range(u(lod)):
                    mesh=mesh_start+n*9;group_start=pointer(mesh+4,mesh);bound(group_start,u(mesh),group_size)
                    for q in range(u(mesh)):
                        group=group_start+q*group_size;headers.append((group,25,group_size));counts['groups']+=1
                        buffer(pointer(group+4,group),u(group),9)
                        buffer(pointer(group+12,group),u(group+8),2)
                        strip_start=pointer(group+20,group);bound(strip_start,u(group+16),strip_size)
                        if group_size==33 and u(group+25):
                            if u(group+29)<33:raise ValueError('Invalid VTX topology offset')
                            bound(group+u(group+29),u(group+25),2)
                            if require_zero:raise ValueError('VTX topology fields are nonzero; cannot discard them for legacy Xbox layout')
                        for s in range(u(group+16)):
                            strip=strip_start+s*strip_size;headers.append((strip,27,strip_size));counts['strips']+=1
                            if data[strip+18]&~3:raise ValueError('Invalid VTX strip flags')
                            if u(strip)+u(strip+4)>u(group+8) or u(strip+8)+u(strip+12)>u(group):
                                raise ValueError('VTX strip exceeds its vertex/index buffers')
                            # An empty bone-state-change table has no readable
                            # buffer; SDK output may leave a stale unused offset.
                            if u(strip+19):buffer(pointer(strip+23,strip),u(strip+19),8)
                            if strip_size==35 and u(strip+27) and require_zero:
                                raise ValueError('VTX strip topology fields are nonzero; cannot discard them')
    return pointers,headers,buffers,counts


def relayout(data,endian,source,target):
    pointers,headers,buffers,counts=layout(data,endian,*source)
    edits=[]
    for start,legacy,size in headers:
        wanted=target[0] if legacy==25 else target[1]
        if size!=wanted:edits.append((start+legacy,size-legacy,b'\0'*(wanted-legacy)))
    edits.sort()
    if len({p for p,_,_ in edits})!=len(edits):raise ValueError('Overlapping VTX header tables')
    def moved(p):
        delta=0
        for start,remove,insert in edits:
            if start<=p<start+remove:raise ValueError('VTX pointer refers to a removed header field')
            if p>=start+remove:delta+=len(insert)-remove
        return p+delta
    for start,size,payload in buffers:
        if any(start<position<start+size or remove and max(start,position)<min(start+size,position+remove)
               for position,remove,insert in edits):raise ValueError('VTX header overlaps geometry/material data')
    output=bytearray();previous=0
    for position,remove,insert in edits:
        if position<previous:raise ValueError('Overlapping VTX layout edits')
        output+=data[previous:position]+insert;previous=position+remove
    output+=data[previous:]
    for field,anchor,original in pointers:
        struct.pack_into(endian+'i',output,moved(field),moved(original)-moved(anchor))
    for start,size,payload in buffers:
        if output[moved(start):moved(start)+size]!=payload:raise ValueError('VTX geometry/material buffer changed')
    if layout(output,endian,*target)[3]!=counts:raise ValueError('VTX model/LOD/group/strip counts changed')
    return bytes(output),{'source_layout':list(source),'target_layout':list(target),**counts,
        'geometry_and_bone_buffers_exact':True,'original_sha256':hashlib.sha256(data).hexdigest(),
        'adapted_sha256':hashlib.sha256(output).hexdigest()}


def prepare_source(data):
    try:layout(data,'<',33,35,require_zero=False)
    except (ValueError,struct.error):
        try:return relayout(data,'<',(25,27),(33,35))
        except struct.error as e:raise ValueError('Truncated VTX structure') from e
    return data,{'source_layout':[33,35],'target_layout':[33,35],'already_sdk_layout':True}


def finish_console(data):
    if len(data)<36:raise ValueError('Truncated console VTX')
    plain=data[:36]+unpack_source(data[36:])
    try:adapted,record=relayout(plain,'>',(33,35),(25,27))
    except struct.error as e:raise ValueError('Truncated console VTX structure') from e
    return adapted[:36]+pack_source(adapted[36:]),record
