"""Recover missing chapter thumbnails from a user's PC installation, without resizing."""
from pathlib import Path
import struct,hashlib
from .archive import Vpk,safe_name

def convert_pc_previews(materials,pc_game,sdk_bin,runtime_bin,work,progress=lambda _:None,cancelled=lambda:False):
    from .core import Backend
    work=Path(work);work.mkdir(parents=True,exist_ok=False)
    wanted={safe_name(n) for n in materials}
    if any(not n.startswith('materials/vgui/maps/') or not n.endswith('.vmt') for n in wanted):
        raise ValueError('PC preview recovery is restricted to chapter thumbnails')
    needed={n[:-4]+'.vtf' for n in wanted};index={}
    for folder in ('left4dead2','left4dead2_dlc1','left4dead2_dlc2','left4dead2_dlc3','update'):
        base=Path(pc_game)/folder
        for path in sorted(base.glob('*_dir.vpk')):
            archive=Vpk(path)
            for name in needed & archive.entries.keys():index[name]=(archive,name)
        for name in needed:
            path=base/name
            if path.is_file() and not path.is_symlink():index[name]=(path,None)
    missing=needed-index.keys()
    if missing:raise ValueError('PC chapter thumbnail not found: '+', '.join(sorted(missing)))
    jobs=[];members={};report={'images':[],'resized':False,'backend':'makegamedata','scope':'Missing chapter previews only'}
    backend=Backend(sdk_bin,runtime_bin,work/'.work',120,jobs)
    try:
        for name in sorted(needed):
            if cancelled():raise InterruptedError('PC chapter preview conversion cancelled')
            source,entry=index[name];raw=source.read(entry) if entry else source.read_bytes()
            if len(raw)<64 or raw[:4]!=b'VTF\0':raise ValueError('Invalid PC chapter thumbnail: '+name)
            dimensions=struct.unpack_from('<2H',raw,16);fmt=struct.unpack_from('<I',raw,52)[0]
            if dimensions!=(256,128) or fmt!=13 or struct.unpack_from('<H',raw,24)[0]!=1:
                raise ValueError('PC chapter thumbnail does not match native 256x128 DXT1 profile: '+name)
            progress('Recovering original PC chapter preview: '+name)
            path=backend.game/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            target=name[:-4]+'.360.vtf';result=backend.run(name,[target])
            if target not in result:raise ValueError('Chapter preview conversion failed: '+name+'; '+jobs[-1].get('error','see logs'))
            data=result[target]
            if struct.unpack_from('>3H',data,20)!=(256,128,1) or struct.unpack_from('>I',data,48)[0]!=13 or data[30]!=0:
                raise ValueError('Chapter preview lost its native dimensions, format or top mip: '+name)
            members[target]=data
            report['images'].append({'material':name[:-4]+'.vmt','source':str(source.path if entry else source),
                'source_sha256':hashlib.sha256(raw).hexdigest(),'target_sha256':hashlib.sha256(data).hexdigest(),
                'dimensions':[256,128],'format':'DXT1','mip_skip':0})
    finally:
        backend.close()
        import json
        (work/'jobs.json').write_text(json.dumps(jobs,indent=2),encoding='utf-8')
    return members,report
