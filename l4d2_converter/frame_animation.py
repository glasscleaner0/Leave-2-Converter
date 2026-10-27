"""Experimental PC frame-rotation adapter, written independently of SDK code.

Reads PC studio v49 containers. Re-encodes sorted-component 48-bit rotations
as the older XYZ/sign-W 48-bit representation before external SDK conversion.
Both representations occupy six bytes: tables, offsets and positions stay put.
This is a quantized representation change, NOT a lossless byte swap.
Format cross-reference: ZeqMacaw/Crowbar SourceQuaternion48bitsViaBytes and
SourceAniFrameAnim49; reference repository/license kept separately in work/.
No Crowbar or MakeGameData implementation is incorporated here.
"""
import math
import struct
from .models import model_info


def sorted_rotation(data):
    if len(data)!=6:raise ValueError('Sorted rotation must contain six bytes')
    words=struct.unpack('<3H',data)
    first=((words[0]>>15)<<1)|(words[1]>>15)
    q=[0.0]*4
    for i,w in enumerate(words):q[(first+i)%4]=((w&32767)-16384)/23168.0
    remaining=1.0-sum(x*x for x in q)
    if remaining < -0.0001:raise ValueError('Invalid sorted rotation magnitude')
    q[(first+3)%4]=math.copysign(math.sqrt(max(0.0,remaining)),-1.0 if words[2]&32768 else 1.0)
    return tuple(q)


def legacy_rotation(data):
    a,b,c=struct.unpack('<3H',data)
    x=(a-32768)/32768.0;y=(b-32768)/32768.0;z=((c&32767)-16384)/16384.0
    w=math.sqrt(max(0.0,1.0-x*x-y*y-z*z))*(-1 if c&32768 else 1)
    length=math.sqrt(x*x+y*y+z*z+w*w)
    return tuple(v/length for v in (x,y,z,w))


def encode_legacy(q):
    if len(q)!=4 or not all(math.isfinite(v) for v in q):raise ValueError('Invalid rotation')
    values=[max(0,min(limit,int(q[i]*scale)+shift)) for i,scale,shift,limit in [(0,32768,32768,65535),(1,32768,32768,65535),(2,16384,16384,32767)]]
    values[2]|=32768 if q[3]<0 else 0
    return struct.pack('<3H',*values)


def downgrade_frame_rotations(mdl,ani=None):
    info=model_info(mdl)
    if info['endian']!='<' or info['version']!=49:raise ValueError('Frame adapter requires a PC v49 model')
    originals={'mdl':mdl}
    if ani is not None:
        if len(ani)<8 or ani[:4]!=b'IDAG' or struct.unpack_from('<I',ani,4)[0]!=49:raise ValueError('Invalid PC animation container')
        originals['ani']=ani
    bones=info['bones'];count,start=struct.unpack_from('<2I',mdl,180);blocks,blockindex=struct.unpack_from('<2I',mdl,352)
    if bones>256 or count>100000 or start+count*100>len(mdl) or blockindex+blocks*8>len(mdl):raise ValueError('Animation table outside model')
    def checked(buf,offset,size,end=None):
        if offset<0 or size<0 or offset+size>min(len(buf),end if end is not None else len(buf)):raise ValueError('Animation payload outside declared block')
    records={}
    for i in range(count):
        d=start+i*100;flags,frames=struct.unpack_from('<2I',mdl,d+12)
        if not flags&64 or flags&32:continue
        if not 1<=frames<=1000000:raise ValueError('Invalid animation frame count')
        block,offset=struct.unpack_from('<2i',mdl,d+52);section,span=struct.unpack_from('<2i',mdl,d+80)
        if span<0:raise ValueError('Invalid animation section span')
        if span:
            n=frames//span+2;checked(mdl,d+section,n*8)
            entries=[(*struct.unpack_from('<2i',mdl,d+section+j*8),min((j+1)*span,frames-1)-min(j*span,frames-1)+1) for j in range(n)]
        else:entries=[(block,offset,frames)]
        for block,offset,nframes in entries:
            if block<0 or (block==0 and offset==0):continue
            if block:
                if not 0<block<blocks or 'ani' not in originals:raise ValueError('Missing animation block file')
                begin,end=struct.unpack_from('<2I',mdl,blockindex+block*8)
                if end<begin:raise ValueError('Reversed animation block')
                container='ani';at=begin+offset
            else:container='mdl';at=d+offset;end=len(mdl)
            buf=originals[container];checked(buf,at,24+bones,end)
            key=(container,at);old=records.get(key)
            if old is None or nframes>old[0]:records[key]=(nframes,end)
    flags_to_change={};rotations=set();hist={}
    for (container,at),(nframes,end) in records.items():
        buf=originals[container];const,frame,stride=struct.unpack_from('<3I',buf,at)
        flags=buf[at+24:at+24+bones];cp=at+const;fp=0;frame_rotations=[]
        for i,f in enumerate(flags):
            hist[hex(f)]=hist.get(hex(f),0)+1
            if f&32:raise ValueError('Full-precision constant positions need a separate layout adapter')
            if (f&64 and f&2) or (f&128 and f&8):raise ValueError('Conflicting rotation encodings')
            if f&64:checked(buf,cp,6,end);rotations.add((container,cp));cp+=6
            if f&2:cp+=6
            if f&1:cp+=6
            if f&128:frame_rotations.append(fp);fp+=6
            if f&8:fp+=6
            if f&4:fp+=6
            if f&16:fp+=12
            if f&192:flags_to_change[(container,at+24+i)]=(f&63)|(2 if f&64 else 0)|(8 if f&128 else 0)
        if const:checked(buf,at+const,cp-(at+const),end)
        elif cp!=at:raise ValueError('Missing constant data offset')
        if stride!=fp:raise ValueError('Frame stride differs from bone layout')
        if stride:
            if not frame:raise ValueError('Missing frame data offset')
            checked(buf,at+frame,stride*nframes,end)
            for f in range(nframes):
                for relative in frame_rotations:rotations.add((container,at+frame+f*stride+relative))
    output={k:bytearray(v) for k,v in originals.items()};max_error=0.0;sum_error2=0.0
    for container,offset in rotations:
        q=sorted_rotation(originals[container][offset:offset+6]);encoded=encode_legacy(q);decoded=legacy_rotation(encoded)
        error=2*math.acos(min(1.0,abs(sum(a*b for a,b in zip(q,decoded)))))
        max_error=max(max_error,error);sum_error2+=error*error
        output[container][offset:offset+6]=encoded
    for (container,offset),value in flags_to_change.items():output[container][offset]=value
    result={k:bytes(v) for k,v in output.items()}
    return result,{'frame_records':len(records),'rotation_samples':len(rotations),'bone_flags_changed':len(flags_to_change),'max_rotation_error_degrees':math.degrees(max_error),'rms_rotation_error_degrees':math.degrees(math.sqrt(sum_error2/max(1,len(rotations)))),'input_bone_flags':hist,'lengths_preserved':all(len(result[k])==len(v) for k,v in originals.items()),'representation':'sorted-48 to legacy-48; small rotation quantization expected','experimental_console_validation_required':True}

