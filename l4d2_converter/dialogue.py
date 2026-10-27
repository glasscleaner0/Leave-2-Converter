"""Reusable validation/manifest helpers for experimental PC dialogue imports."""
import struct
from .keyvalues import parse,Token,decode_text
from .archive import safe_name


def validate_scene_image(data):
    if len(data)<20 or data[:4] not in (b'VSIF',b'FISV'):raise ValueError('Invalid scene image header')
    endian='<' if data[:4]==b'VSIF' else '>'
    _,version,count,strings,entries=struct.unpack_from(endian+'5I',data)
    if version!=3 or count>1000000 or strings>65535:raise ValueError('Unsupported scene image version/count')
    if not 20+strings*4<=entries or entries+count*16>len(data):raise ValueError('Scene image tables outside file')
    crcs=[]
    for i in range(count):
        crc,offset,size,summary=struct.unpack_from(endian+'4I',data,entries+i*16)
        if not size or offset<entries+count*16 or offset+size>len(data) or not entries+count*16<=summary<len(data):raise ValueError('Scene image payload outside file')
        crcs.append(crc)
    if crcs!=sorted(crcs) or len(set(crcs))!=count:raise ValueError('Scene image CRC index is not strictly sorted')
    for i in range(strings):
        at=struct.unpack_from(endian+'I',data,20+i*4)[0]
        if not 20+strings*4<=at<entries or data.find(b'\0',at,entries)<0:raise ValueError('Scene image string outside pool')
    return {'version':version,'scenes':count,'strings':strings,'bytes':len(data),'endian':endian,'crc_order_validated':True,'all_entry_payloads_and_string_offsets_bounded':True}


def extend_sound_manifest(data,files):
    text=decode_text(data);root=parse(text)
    if len(root)!=1 or root[0].key.value.lower()!='game_sounds_manifest' or not isinstance(root[0].value,list):raise ValueError('Invalid sound manifest')
    existing={e.value.value.lower().replace('\\','/') for e in root[0].value if isinstance(e.value,Token)}
    added=[]
    for name in sorted(set(files)):
        name=safe_name(name)
        if not name.startswith('scripts/') or not name.endswith('.txt'):raise ValueError('Invalid sound script path')
        if name.lower() not in existing:added.append(name);existing.add(name.lower())
    if not added:return data,[]
    closing=text.rfind('}');assert closing>=0
    insert='\n'+''.join(' "precache_file" "'+n+'"\n' for n in added)
    output=(text[:closing]+insert+text[closing:]).encode('utf-8');parse(output.decode('utf-8'))
    return output,added

def response_rule_files(root,read):
    """Collect the PC response-rule include closure without rewriting its grammar."""
    import re
    from .dependencies import reference_name
    files={};active=set()
    def visit(name):
        name=reference_name(name,'scripts')
        if name in active:raise ValueError('Response-rule include cycle at '+name)
        if name in files:return
        active.add(name);data=read(name)
        if data is None:raise ValueError('Missing response-rule include '+name)
        files[name]=data;text=decode_text(data)
        for child in re.findall(r'^\s*#include\s+"([^"\r\n]+)"',text,re.M):
            child=child.lower().replace('\\','/')
            if child.startswith('scripts/'):target=child
            elif child.startswith('talker/'):target='scripts/'+child
            else:target=name.rsplit('/',1)[0]+'/'+child
            visit(target)
        active.remove(name)
    visit(root)
    return files
