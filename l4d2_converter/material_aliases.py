"""Opt-in asset aliases for material trees; keeps shaders and patch semantics."""
import hashlib
from .archive import safe_name
from .dependencies import TEXTURES,reference_name
from .keyvalues import parse,Token,decode_text


def alias_material_tree(roots,read,scope):
    scope=safe_name(scope).strip('/')
    if not scope or '.' in scope.split('/')[-1]:raise ValueError('Invalid material alias scope')
    result={};textures={};includes={};visiting=set();built={};changes=[]
    def alias(name,kind):
        token=hashlib.sha256(name.encode('utf-8')).hexdigest()[:24]
        return 'materials/'+scope+'/'+kind+'_'+token+('.vtf' if kind=='texture' else '.vmt')
    def texture(value,owner):
        if value.lower()=='env_cubemap' or value.startswith('$'):return value
        name=value.lower().replace('\\','/')
        if not name.startswith('materials/'):name='materials/'+name
        if not name.endswith('.vtf'):name+='.vtf'
        name=reference_name(name,'materials')
        if name not in textures:
            data=read(name)
            if data is None:raise ValueError('Missing PC texture '+name+' referenced by '+owner)
            textures[name]=alias(name,'texture');result[textures[name]]=data
        return textures[name].removeprefix('materials/').removesuffix('.vtf')
    def visit(name):
        name=reference_name(name,'materials')
        if name in visiting:raise ValueError('Material include cycle at '+name)
        if name in built:return built[name]
        visiting.add(name);data=read(name)
        if data is None:raise ValueError('Missing PC material '+name)
        text=decode_text(data);tree=parse(text);edits=[]
        def walk(entries):
            for e in entries:
                if isinstance(e.value,list):walk(e.value);continue
                if not isinstance(e.value,Token):continue
                key=e.key.value.lower();old=e.value.value;new=None
                if key=='include':
                    child=old.lower().replace('\\','/')
                    if not child.startswith('materials/'):child='materials/'+child
                    if not child.endswith('.vmt'):child+='.vmt'
                    child=reference_name(child,'materials');body=visit(child)
                    includes.setdefault(child,alias(child,'include'));result[includes[child]]=body;new=includes[child]
                elif key in TEXTURES:new=texture(old,name)
                if new is not None and new!=old:
                    edits.append((e.value.start,e.value.end,'"'+new+'"'));changes.append({'material':name,'key':key,'before':old,'after':new})
        walk(tree)
        for start,end,value in sorted(edits,reverse=True):text=text[:start]+value+text[end:]
        parse(text);visiting.remove(name);built[name]=text.encode('utf-8');return built[name]
    for name in sorted(set(roots)):result[name]=visit(name)
    return result,{'roots':len(set(roots)),'included_materials':len(includes),'textures':len(textures),'texture_aliases':textures,'include_aliases':includes,'changes':changes,'shaders_and_patch_structure_preserved':True,'scope':scope}
