"""Lossless PC intensity-texture staging adapters; external SDK does conversion."""
import hashlib
import struct
from .textures import texture_info

def legacy_ui_mips(data):
    """Stage lower RGB mips for the old SDK, retaining the original top image.

    This is an SDK workaround for valid single-mip NOMIP UI sources, not a
    general VTF repair. Added mips use rounded channel-space 2x2 box averages.
    """
    if len(data)<80 or data[:4]!=b'VTF\0':return None
    major,minor,header=struct.unpack_from('<3I',data,4)
    fmt=struct.unpack_from('<I',data,52)[0]
    width,height=struct.unpack_from('<2H',data,16)
    flags=struct.unpack_from('<I',data,20)[0]
    if major!=7 or minor!=2 or fmt not in (2,3) or data[56]!=1 or not flags&0x100:return None
    if max(width,height)<=512:return None
    if (not width or not height or max(width,height)>4096 or width&(width-1) or height&(height-1)
        or struct.unpack_from('<H',data,24)[0]!=1 or struct.unpack_from('<H',data,63)[0]!=1 or flags&0x4000):
        raise ValueError('Legacy UI mip adapter requires bounded power-of-two single-frame 2D RGB')
    if not 80<=header<=len(data):raise ValueError('Invalid legacy UI VTF header')
    lw,lh=data[61:63];lowfmt=struct.unpack_from('<I',data,57)[0]
    if bool(lw)!=bool(lh) or (lw and (lowfmt!=13 or lw>16 or lh>16)):raise ValueError('Unsupported legacy UI thumbnail')
    off=header+(((lw+3)//4)*((lh+3)//4)*8 if lw else 0)
    if off+width*height*3!=len(data):raise ValueError('Legacy UI RGB payload is truncated or has unknown trailing data')
    w,h=width,height;levels=[data[off:]]
    while w>1 or h>1:
        prev=levels[-1];nw,nh=max(1,w//2),max(1,h//2);small=bytearray(nw*nh*3)
        for y in range(nh):
            for x in range(nw):
                indices=[(yy*w+xx)*3 for yy in range(y*2,min(h,y*2+2)) for xx in range(x*2,min(w,x*2+2))]
                for channel in range(3):
                    small[(y*nw+x)*3+channel]=(sum(prev[i+channel] for i in indices)+len(indices)//2)//len(indices)
        levels.append(bytes(small));w,h=nw,nh
    head=bytearray(data[:off]);head[56]=len(levels)
    staged=bytes(head)+b''.join(reversed(levels))
    return staged,{'method':'legacy_ui_sdk_mip_staging','width':width,'height':height,'flags':flags,
        'source_format':fmt,'source_mips':1,'staged_mips':len(levels),'top_image_sha256':hashlib.sha256(levels[0]).hexdigest(),
        'source_top_image_preserved':True,'added_mips':'rounded_channel_space_2x2_box','source_sha256':hashlib.sha256(data).hexdigest()}

def retry_legacy_ui(name,payload,backend):
    if not name.startswith('materials/vgui/'):return {},None
    adapted=legacy_ui_mips(payload)
    if adapted is None:return {},None
    staged,record=adapted
    alias='materials/__converter_input/uimips_'+hashlib.sha256(name.encode()).hexdigest()[:16]+'.vtf'
    expected=alias[:-4]+'.360.vtf';path=backend.game/alias
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(staged)
    try:
        output=backend.run(alias,[expected])
        if not output:return {},None
        info=texture_info(output[expected])
        if info['frames']!=1 or info['depth']!=1 or (info['flags']^record['flags'])&(0x100|0x200|0x4000):
            raise ValueError('SDK legacy UI retry changed texture semantics')
        if not (0<info['width']<=record['width'] and 0<info['height']<=record['height']) or info['width']*record['height']!=info['height']*record['width']:
            raise ValueError('SDK legacy UI retry changed aspect ratio or enlarged texture')
        record.update(path=name,staged_sha256=hashlib.sha256(staged).hexdigest(),output_width=info['width'],output_height=info['height'],sdk_mip_skip=info['mip_skip'],hardware_tested=False)
        return {name[:-4]+'.360.vtf':output[expected]},record
    finally:
        path.unlink(missing_ok=True);(backend.game/expected).unlink(missing_ok=True)

def expand_intensity(data):
    if len(data)<64 or data[:4]!=b'VTF\0':return None
    major,minor,header=struct.unpack_from('<3I',data,4)
    fmt=struct.unpack_from('<I',data,52)[0]
    if fmt not in (5,6):return None
    if major!=7 or not 1<=minor<=5 or not (64 if minor==1 else 80)<=header<=len(data):
        raise ValueError('Unsupported intensity VTF header')
    width,height=struct.unpack_from('<2H',data,16)
    flags=struct.unpack_from('<I',data,20)[0]
    frames=struct.unpack_from('<H',data,24)[0]
    depth=1 if minor==1 else struct.unpack_from('<H',data,63)[0]
    mips=data[56]
    if not width or not height or frames!=1 or depth!=1 or flags&0x4000 or not 1<=mips<=max(width,height).bit_length():
        raise ValueError('Intensity adapter requires a valid single-frame 2D texture')
    entries=[]
    if minor>=3:
        count=struct.unpack_from('<I',data,68)[0]
        if count>32 or 80+count*8>header:raise ValueError('Invalid VTF resource directory')
        image=None
        for i in range(count):
            p=80+i*8;tag=data[p:p+3];inline=data[p+3]&2;off=struct.unpack_from('<I',data,p+4)[0]
            if tag==b'CRC':raise ValueError('Intensity VTF with derived CRC metadata is not supported yet')
            if not inline:
                if not header<=off<len(data):raise ValueError('VTF resource outside payload')
                entries.append((p,off))
            if tag==b'\x30\0\0':
                if inline or image is not None:raise ValueError('Invalid image resource')
                image=off
        if image is None:raise ValueError('Missing VTF image resource')
    else:
        lw,lh=data[61:63];lowfmt=struct.unpack_from('<I',data,57)[0]
        if lw and lh and lowfmt!=13:raise ValueError('Unsupported legacy VTF thumbnail format')
        image=header+(((lw+3)//4)*((lh+3)//4)*8 if lw and lh else 0)
    pixels=sum(max(1,width>>i)*max(1,height>>i) for i in range(mips))
    if pixels*4>64*1024**2:raise ValueError('Intensity expansion exceeds 64 MiB')
    end=image+pixels*(1 if fmt==5 else 2)
    if end>len(data) or any(image<off<end for _,off in entries):
        raise ValueError('Truncated/overlapping VTF image payload')
    raw=data[image:end];rgba=bytearray(pixels*4)
    for i in range(pixels):
        value=raw[i if fmt==5 else i*2]
        rgba[i*4:i*4+4]=bytes((value,value,value,255 if fmt==5 else raw[i*2+1]))
    result=bytearray(data[:image]+rgba+data[end:]);struct.pack_into('<I',result,52,0)
    delta=len(rgba)-len(raw)
    for p,off in entries:
        if off>=end:struct.pack_into('<I',result,p+4,off+delta)
    return bytes(result),{'source_format':fmt,'staged_format':0,'width':width,'height':height,'mips':mips,'frames':frames,'flags':flags,'pixels':pixels,'method':'lossless_intensity_to_rgba8888'}

def retry_intensity(name,payload,backend):
    adapted=expand_intensity(payload)
    if adapted is None:return {},None
    staged,record=adapted
    alias='materials/__converter_input/intensity_'+hashlib.sha256(name.encode()).hexdigest()[:16]+'.vtf'
    expected=alias[:-4]+'.360.vtf';target=name[:-4]+'.360.vtf'
    path=backend.game/alias;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(staged)
    try:
        output=backend.run(alias,[expected])
        if not output:return {},None
        info=texture_info(output[expected])
        if (info['width'],info['height'],info['frames'],info['depth'])!=(record['width'],record['height'],1,1) or (info['flags']^record['flags'])&(0x100|0x4000|0x2000):
            raise ValueError('SDK intensity retry changed texture semantics')
        record.update(path=name,source_sha256=hashlib.sha256(payload).hexdigest(),staged_sha256=hashlib.sha256(staged).hexdigest(),hardware_tested=False)
        return {target:output[expected]},record
    finally:
        path.unlink(missing_ok=True);(backend.game/expected).unlink(missing_ok=True)
