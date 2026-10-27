"""Collect NAV-selected infected populations and their runtime model dependencies."""
import re
import struct
from pathlib import Path
from .keyvalues import parse,Token,decode_text
from .archive import safe_name
from .formats import unpack_source


def nav_population(data):
    data=unpack_source(data)
    endian='>' if data[:4]==bytes.fromhex('feedface') else '<'
    if len(data)<19 or struct.unpack_from(endian+'I',data)[0]!=0xfeedface:
        raise ValueError('Invalid population NAV header')
    if struct.unpack_from(endian+'II',data,4) not in ((16,14),(15,13)):
        raise ValueError('Unsupported population NAV layout')
    pos=17
    def u16():
        nonlocal pos
        if pos+2>len(data):raise ValueError('Truncated population NAV')
        value=struct.unpack_from(endian+'H',data,pos)[0];pos+=2;return value
    def string(size=None):
        nonlocal pos
        end=data.find(b'\0',pos) if size is None else pos+size
        if end<pos or end>len(data):raise ValueError('Truncated population NAV string')
        result=data[pos:end].rstrip(b'\0').decode('ascii');pos=end+(size is None)
        return result
    places=[]
    for _ in range(u16()):places.append(string(u16()))
    if pos>=len(data):raise ValueError('Truncated population NAV flags')
    pos+=1
    population=string()
    return {'population':population or 'default','places':places}


def population_blocks(data):
    text=decode_text(data);roots=parse(text)
    if len(roots)!=1 or roots[0].key.value.lower()!='population' or not isinstance(roots[0].value,list):
        raise ValueError('Expected one Population block')
    blocks={}
    for e in roots[0].value:
        key=e.key.value.lower()
        if key in blocks:raise ValueError('Duplicate population '+key)
        if not isinstance(e.value,list):raise ValueError('Population definition is not a block: '+key)
        blocks[key]=e
    return blocks


def population_text(blocks):
    def quoted(value):
        if any(c in value for c in ('"','\0','\n','\r')):raise ValueError('Unsafe population token')
        return '"'+value+'"'
    def render(entries,indent):
        result=[]
        for e in entries:
            if isinstance(e.value,list):result.extend([indent+quoted(e.key.value),'%s{'%indent,render(e.value,indent+'\t'),indent+'}'])
            else:result.append(indent+quoted(e.key.value)+' '+quoted(e.value.value))
        return '\n'.join(result)
    return ('"Population"\n{\n'+render(list(blocks.values()),'\t')+'\n}\n').encode('utf-8')


def stage_populations(refs,navs,destination,base_population=None):
    """Merge selected PC tables into a user-owned console baseline; stage missing MDLs.

    Call once for the union of campaigns so a single shared support addon owns
    population.txt. Existing unrelated population definitions are preserved.
    Normal converter discovery resolves MDL companions and materials afterward.
    """
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    source=refs.pc_read('scripts/population.txt')
    if source is None:raise ValueError('PC population.txt missing')
    pc=population_blocks(source)
    base=population_blocks(base_population if base_population is not None else refs.xbox_read('scripts/population.txt'))
    selected=set();metadata=[]
    for owner,data in navs.items():
        row=nav_population(data);metadata.append(dict(path=owner,**row))
        selected.add(row['population'].lower());selected.update(p.lower() for p in row['places'] if p)
    # Mob variants are selected dynamically after the NAV's base population.
    for name in list(selected):
        if name+'_mob' in pc:selected.add(name+'_mob')
    models=set();tables=[]
    for name in sorted(selected):
        entry=pc.get(name) or base.get(name)
        if entry is None:raise ValueError('NAV-selected population definition missing: '+name)
        base[name]=entry;tables.append(name)
        for item in entry.value:
            if not isinstance(item.value,Token) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',item.value.value):
                raise ValueError('Unsupported population model weight: '+name+'/'+item.key.value)
            if float(item.value.value)==0:continue
            stem=item.key.value
            if not re.fullmatch('[A-Za-z0-9_]+',stem):raise ValueError('Unsafe infected model name: '+stem)
            models.add('models/infected/'+stem.lower()+'.mdl')
    files=[];native=[]
    for name in sorted(models):
        if name in refs.xbox:native.append(name);continue
        data=refs.pc_read(name)
        if data is None:raise ValueError('Population-selected infected model missing: '+name)
        target=destination/safe_name(name);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);files.append(name)
    target=destination/'scripts/population.txt';target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(population_text(base))
    return {'navigation':metadata,'selected_tables':tables,'model_references':sorted(models),'staged_models':files,'native_models':native,'global_definitions_preserved':True}