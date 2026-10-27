"""Leave 2 Loader output and optional previews; external tools stay external."""
from pathlib import Path
import hashlib
import os
import re
import shutil
import struct
import subprocess
from .archive import aligned_zip, safe_name
from .keyvalues import parse, decode_text, Token
from .textures import texture_info

PREVIEW_SIZE = 128

def addon_metadata(data, fallback):
    if not data:
        return {'addontitle':fallback}, []
    try:
        blocks=[e for e in parse(decode_text(data)) if e.key.value.casefold()=='addoninfo' and isinstance(e.value,list)]
        if len(blocks)!=1:raise ValueError('Expected one AddonInfo block')
        fields={e.key.value.lower():e.value.value for e in blocks[0].value
                if isinstance(e.value,Token) and e.key.value.lower().startswith('addon')}
        fields.setdefault('addontitle',fallback)
        return fields, []
    except ValueError as error:
        return {'addontitle':fallback}, ['Addon metadata could not be parsed; using the input name: '+str(error)]

def addon_identifier(input_path, fields):
    path=Path(input_path);stem=path.stem if path.is_file() or path.suffix.lower()=='.vpk' else path.name
    title=fields.get('addontitle','').strip()
    if title.isdecimal():title=''
    label=title or (stem if not stem.isdecimal() else 'Addon')
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', label).strip(' .')[:80].rstrip(' .')
    if not name:name='Addon'
    try:safe_name(name)
    except ValueError:name='Addon_'+name
    if name.casefold() in {'logs','install','report','resources'}:name='Addon_'+name
    return name

def preview_identity(identifier, preview):
    """Stable cache name, isolated by addon identity and converted image bytes.

    A folder can be renamed after conversion; generic original names must not
    alias a different image in VGUI's shared material/image cache.
    """
    digest=hashlib.sha256(identifier.casefold().encode('utf-8')+b'\0'+preview).hexdigest()
    return 'l2c_p_'+digest[:24]


def metadata_bytes(fields, identifier, preview, preview_name=None):
    def clean(value):return str(value).replace('\0','').replace('"',"'").replace('\r','')
    fields={k:v for k,v in fields.items() if re.fullmatch('[a-z_][a-z0-9_]*',k)}
    fields.update(leave2_managed='1',leave2_preview=f'leave2/addons/{preview_name or identifier}' if preview else '')
    text='"AddonInfo"\n{\n'+''.join(f'  "{k}" "{clean(v)}"\n' for k,v in fields.items())+'}\n'
    parse(text)
    return text.encode('utf-8')

def preview_source(input_path, game):
    path=Path(input_path);game=Path(game)
    # Steam's same-name JPG beside the selected VPK has first priority.
    if path.is_file() and path.suffix.casefold()=='.vpk':
        for extension in ('.jpg','.jpeg'):
            matches=[p for p in path.parent.iterdir() if p.is_file() and p.name.casefold()==(path.stem+extension).casefold()]
            if len(matches)>1:raise ValueError('Ambiguous same-name addon preview: '+path.stem+extension)
            if matches:return matches[0], 'sidecar'+extension
    # Embedded VTF then embedded JPG. Retain PNG as a final compatibility fallback.
    for name in ('addonimage.vtf','addonimage.jpg','addonimage.jpeg','addonimage.png'):
        candidate=game/name
        if candidate.is_file():return candidate, 'embedded'+candidate.suffix
    if path.is_file():
        for extension in ('.png',):
            matches=[p for p in path.parent.iterdir() if p.is_file() and p.name.casefold()==(path.stem+extension).casefold()]
            if len(matches)>1:raise ValueError('Ambiguous same-name addon preview: '+path.stem+extension)
            if matches:return matches[0], 'sidecar'+extension
    return None, 'none'

def rgba_vtf(rgba, size=PREVIEW_SIZE):
    if len(rgba)!=size*size*4:raise ValueError('Preview decoder returned an unexpected pixel count')
    header=bytearray(80);header[:4]=b'VTF\0'
    struct.pack_into('<3I',header,4,7,2,80)
    struct.pack_into('<2H',header,16,size,size)
    struct.pack_into('<I',header,20,0x230c) # clamp, no mips/LOD, alpha
    struct.pack_into('<H',header,24,1)
    struct.pack_into('<f',header,48,1.0)
    struct.pack_into('<I',header,52,0) # IMAGE_FORMAT_RGBA8888
    header[56]=1
    struct.pack_into('<I',header,57,0xffffffff)
    struct.pack_into('<H',header,63,1)
    return bytes(header)+rgba

def decode_image(source, decoder='', timeout=120):
    source=Path(source)
    if source.stat().st_size>32*1024**2:raise ValueError('Preview image exceeds the 32 MiB input limit')
    if source.suffix.lower()=='.png':
        with source.open('rb') as handle:header=handle.read(33)
        if len(header)!=33 or header[:8]!=b'\x89PNG\r\n\x1a\n' or header[12:16]!=b'IHDR':raise ValueError('Invalid PNG preview header')
        width,height=struct.unpack_from('>2I',header,16)
        if not width or not height or width*height>16*1024**2:raise ValueError('PNG preview dimensions exceed the 16-megapixel limit')
    executable=decoder or shutil.which('ffmpeg')
    if not executable or not Path(executable).is_file():raise ValueError('PNG/JPG previews need FFmpeg: choose it in the FFmpeg field or install it on PATH')
    filters=f'format=rgba,scale={PREVIEW_SIZE}:{PREVIEW_SIZE}:force_original_aspect_ratio=decrease,pad={PREVIEW_SIZE}:{PREVIEW_SIZE}:(ow-iw)/2:(oh-ih)/2:color=0x00000000'
    result=subprocess.run([str(executable),'-v','error','-nostdin','-max_alloc','67108864','-i',str(source),
        '-vf',filters,'-frames:v','1','-f','rawvideo','-pix_fmt','rgba','pipe:1'],capture_output=True,timeout=min(timeout,60),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if result.returncode:raise ValueError('Preview image decode failed: '+result.stderr.decode(errors='replace')[-400:])
    return rgba_vtf(result.stdout)

def build_preview(input_path, backend, identifier, decoder='', timeout=120):
    info={'status':'none','source':None};warnings=[];target=None;expected=None;first_job=len(backend.rows);created=False
    try:
        source,kind=preview_source(input_path,backend.game)
        if source is None:return None,info,warnings
        info.update(source=str(source),kind=kind,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        payload=source.read_bytes() if source.suffix.lower()=='.vtf' else decode_image(source,decoder,timeout)
        logical=f'materials/__converter_input/loader-preview-{hashlib.sha256(identifier.encode()).hexdigest()[:16]}.vtf'
        expected=logical[:-4]+'.360.vtf';target=backend.game/logical
        if target.exists() or (backend.game/expected).exists():raise ValueError('Preview staging path collides with an existing input asset')
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(payload);created=True
        outputs=backend.run(logical,[expected])
        if expected not in outputs:raise ValueError('MakeGameData did not produce the addon preview; see its optional preview job log')
        converted=outputs[expected];texture=texture_info(converted)
        if max(texture['width'],texture['height'])>512 or texture['frames']!=1 or texture['depth']!=1 or texture['flags']&0x4000:
            raise ValueError('Converted menu preview must be a single 2D image no larger than 512x512; use a same-name PNG to resize it')
        info.update(status='converted',texture=texture,output_sha256=hashlib.sha256(converted).hexdigest())
        return converted,info,warnings
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        info.update(status='omitted',reason=str(error));warnings.append('Optional Leave 2 Loader preview omitted: '+str(error))
        return None,info,warnings
    finally:
        for row in backend.rows[first_job:]:row.update(optional=True,purpose='leave2-loader-preview')
        if created:
            target.unlink(missing_ok=True)
            (backend.game/expected).unlink(missing_ok=True)

def write_loader_output(output, input_path, game, archive, loose, backend, decoder='', timeout=120, progress=print, check_cancel=lambda:None):
    game=Path(game);metadata=game/'addoninfo.txt'
    fields,warnings=addon_metadata(metadata.read_bytes() if metadata.is_file() else None,Path(input_path).stem)
    from .survivor_requirements import requires_l4d1,NOTE
    crew_missions=[name for name,data in loose.items() if name.startswith('missions/') and name.endswith('.txt') and requires_l4d1(data)]
    if crew_missions:
        fields['leave2_requires_l4d1_survivors']='1';warnings.append(NOTE)
    identifier=addon_identifier(input_path,fields)
    progress('Preparing Leave 2 Loader metadata and optional addon preview...')
    preview,preview_info,preview_warnings=build_preview(input_path,backend,identifier,decoder,timeout)
    preview_name=preview_identity(identifier,preview) if preview is not None else None
    if preview_name:preview_info['cache_key']='leave2/addons/'+preview_name
    warnings.extend(preview_warnings)
    for note in warnings:progress(note)
    check_cancel()
    folder=Path(output)/identifier;folder.mkdir()
    (folder/'zip0.360.zip').write_bytes(archive)
    for name,data in loose.items():
        path=folder/safe_name(name);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    (folder/'addoninfo.txt').write_bytes(metadata_bytes(fields,identifier,preview is not None,preview_name))
    if crew_missions:(folder/'L4D1-SURVIVOR-SUPPORT.txt').write_text(NOTE+'\n\nMissions:\n'+'\n'.join(crew_missions)+'\n',encoding='utf-8')
    if preview is not None:
        stem=f'materials/vgui/leave2/addons/{preview_name}'
        material=('"UnlitGeneric"\n{\n "$basetexture" "vgui/leave2/addons/'+preview_name+'"\n "$translucent" "1"\n "$vertexcolor" "1"\n "$vertexalpha" "1"\n "$ignorez" "1"\n}\n').encode()
        ui=folder/'ui';ui.mkdir();(ui/'zip0.360.zip').write_bytes(aligned_zip({stem+'.360.vtf':preview,stem+'.vmt':material}))
    return folder,{'addon_id':identifier,'folder':folder.name,'preview':preview_info,'warnings':warnings,'runtime':'Leave 2 Loader with addon-priority engine patch','addonlist_written':False,'requires_l4d1_survivor_support':bool(crew_missions)}

def install_text(folder, diagnostic=''):
    return (diagnostic+'Leave 2 Loader addon output\n\n'+
        f'Copy the entire {folder}/ folder into left4dead2/addons/ in your Loader-equipped Xbox game.\n'+
        'Requires Leave 2 Loader and its addon-priority engine patch. This converter does not install game patches.\n'+
        'Keep your existing addonlist.txt. After copying, use Register installed addons on the Test tab.\n'+
        'Registration adds new addons as enabled and preserves existing choices. Change the checkbox in game, then fully restart.\n'+
        'The addon folder contains its own zip0.360.zip and any loose maps/missions. Do not move that ZIP into the game root.\n'+
        'Preview files, when available, live in ui/zip0.360.zip so the menu can show them while the addon is disabled.\n'+
        'Remove an older legacy/root-ZIP copy separately to avoid duplicate content. Preserve other addons and saved states.\n'+
        'Conversion and format checks do not guarantee runtime compatibility. See report.json for preview provenance and warnings.\n')
