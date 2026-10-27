"""Reported repairs in private PC DLC staging directories only."""
from pathlib import Path
import hashlib
import re
import struct
from .formats import bsp_lump,bsp_rows
from .keyvalues import tokens,decode_text
from .compatibility import replace_entity_lump


def repair_melee_placeholders(game):
    rows=[]
    for path in (Path(game)/'maps').glob('*.bsp'):
        original=path.read_bytes();entity=bsp_lump(original,0);count=0
        def fix(match):
            nonlocal count
            block=match.group(0)
            fields={k.lower():v.lower() for k,v in re.findall(rb'"([^"\r\n]+)"\s*"([^"\r\n]*)"',block)}
            if fields.get(b'classname')!=b'weapon_melee_spawn' or fields.get(b'model')!=b'models/w_models/weapons/w_pistol_1911.mdl':return block
            # A melee spawner selects its actual model from its melee script.
            result,n=re.subn(rb'"model"\s*"models/w_models/weapons/w_pistol_1911\.mdl"',b'',block,flags=re.I)
            count+=n;return result
        updated=re.sub(rb'\{[^{}]*\}',fix,entity)
        if count:
            path.write_bytes(replace_entity_lump(original,updated))
            rows.append({'path':path.relative_to(game).as_posix(),'method':'remove-stale-melee-editor-model',
                'entities':count,'reason':'Retain weapon_melee_spawn and its selection; let the engine assign its actual melee model'})
    return rows


def ascii_material_paths(game):
    """Rename non-ASCII VMT/VTF pairs and rewrite indexed BSP material names."""
    game=Path(game);mapping={};renames=[];rows=[]
    for path in game.rglob('*'):
        if not path.is_file():continue
        name=path.relative_to(game).as_posix()
        if name.isascii():continue
        if not name.startswith('materials/') or path.suffix.lower() not in ('.vmt','.vtf'):
            raise ValueError('Unsupported non-ASCII runtime asset: '+ascii(name))
        stem=name.removeprefix('materials/').rsplit('.',1)[0].lower()
        alias=mapping.setdefault(stem,'l2pc/material_'+hashlib.sha256(stem.encode()).hexdigest()[:20])
        target=game/('materials/'+alias+path.suffix.lower())
        if target.exists():raise ValueError('ASCII asset alias collides with an existing input')
        renames.append((path,target,name))
    if not mapping:return rows
    def replacement(value):
        original_value=value
        value=value.replace('\\','/');prefix='materials/' if value.lower().startswith('materials/') else ''
        logical=value[len(prefix):];extension=''
        if logical.lower().endswith(('.vmt','.vtf')):logical,extension=logical[:-4],logical[-4:].lower()
        alias=mapping.get(logical.lower())
        return prefix+alias+extension if alias else original_value
    def rewrite_text(data):
        text=decode_text(data);edits=[]
        for token in tokens(text):
            changed=replacement(token.value)
            if changed!=token.value:edits.append((token.start,token.end,'"'+changed+'"'))
        for start,end,value in reversed(edits):text=text[:start]+value+text[end:]
        return text.encode('utf-8') if edits else data
    for path in game.rglob('*.vmt'):
        original=path.read_bytes();changed=rewrite_text(original)
        if changed!=original:path.write_bytes(changed)
    for path in (game/'maps').glob('*.bsp'):
        original=path.read_bytes();entity=bsp_lump(original,0);changed_entity=rewrite_text(entity.rstrip(b'\0'))+b'\0'
        data=replace_entity_lump(original,changed_entity) if changed_entity!=entity else original
        strings=bsp_lump(original,43);table=bsp_lump(original,44)
        if len(table)%4:raise ValueError('Invalid BSP texture string index')
        newstrings=bytearray();newtable=bytearray();changed=False
        for position in range(0,len(table),4):
            offset=struct.unpack_from('<I',table,position)[0];end=strings.find(b'\0',offset)
            if not 0<=offset<=end<len(strings):raise ValueError('Invalid BSP texture string offset')
            name=decode_text(strings[offset:end]);newname=replacement(name);changed|=name!=newname
            newtable.extend(struct.pack('<I',len(newstrings)));newstrings.extend(newname.encode('cp1252')+b'\0')
        if changed:
            rebuilt=bytearray(data)
            for index,payload in ((43,newstrings),(44,newtable)):
                rebuilt.extend(bytes((-len(rebuilt))%4));offset=len(rebuilt);rebuilt.extend(payload)
                version=bsp_rows(original)[index][2]
                row=(offset,len(payload),version,0)
                if struct.unpack_from('<I',original,4)[0]==21:row=(version,offset,len(payload),0)
                struct.pack_into('<4I',rebuilt,8+16*index,*row)
            data=bytes(rebuilt)
            # Every other lump, including absolute static-prop offsets, is retained.
            for index in range(64):
                if index not in (0,43,44) and bsp_lump(data,index)!=bsp_lump(original,index):raise ValueError('ASCII alias changed unrelated BSP data')
        if data!=original:path.write_bytes(data)
    for source,target,name in renames:
        target.parent.mkdir(parents=True,exist_ok=True);source.rename(target)
        rows.append({'path':name,'target':target.relative_to(game).as_posix(),'method':'ascii-material-path',
            'reason':'Xbox ZIP names require ASCII; material references and BSP texture indices rewritten',
            'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    return rows
