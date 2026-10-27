"""Opt-in staging repairs. No original inputs or proprietary tool code are edited."""
import hashlib
import re
import struct
from pathlib import Path
from .formats import bsp_lump, static_prop_summary
from .models import model_info
from .keyvalues import parse, tokens, decode_text, mission_maps
from .archive import XboxZip


def digest(data):
    return hashlib.sha256(data).hexdigest()


def entry_end(text, entry):
    if not isinstance(entry.value, list):
        return entry.value.end
    depth = 0
    for token in tokens(text):
        if token.start <= entry.key.start or token.kind != 'brace':
            continue
        depth += 1 if token.value == '{' else -1
        if depth == 0:
            return token.end
    raise ValueError('Unclosed mission entry')


def repair_mission_mode_braces(data):
    """Repair only an unclosed mode followed by a recognizable sibling mode."""
    text=decode_text(data)
    try:parse(text);return data,[]
    except ValueError as error:
        if not str(error).startswith('Unclosed KeyValues block'):raise
        original_error=error
    ts=tokens(text);stack=[];edits=[]
    known={'coop','versus','survival','scavenge','realism','realismversus'}
    deficit=sum(t.kind=='brace' and t.value=='{' for t in ts)-sum(t.kind=='brace' and t.value=='}' for t in ts)
    for i,t in enumerate(ts):
        if (t.kind!='brace' and t.value.lower() in known and i+1<len(ts) and ts[i+1].value=='{' and
            len(stack)==3 and stack[:2]==['mission','modes'] and stack[-1] in known and
            stack[-1]!=t.value.lower() and i and ts[i-1].kind=='brace' and ts[i-1].value=='}'):
            edits.append({'position':t.start,'previous_mode':stack[-1],'next_mode':t.value.lower(),
                          'line':text.count('\n',0,t.start)+1})
            stack.pop()
        if t.kind=='brace':
            if t.value=='{':stack.append(ts[i-1].value.lower() if i else '')
            elif stack:stack.pop()
            else:raise original_error
    if not edits or deficit!=len(edits) or stack:raise original_error
    for e in reversed(edits):text=text[:e['position']]+'}\n'+text[e['position']:]
    parse(text)
    return text.encode('utf8' if _is_utf8(data) else 'cp1252',errors='surrogateescape'),edits


def prune_mission(data, available):
    """Prune unavailable chapter blocks, preserving other text and metadata."""
    text=decode_text(data);root=parse(text)
    if len(root)!=1 or not isinstance(root[0].value,list):
        raise ValueError('Mission must contain one root block')
    edits=[];removed=[]
    for field in root[0].value:
        if field.key.value.lower()!='modes' or not isinstance(field.value,list):continue
        for mode in field.value:
            if not isinstance(mode.value,list):continue
            local=[];kept=0
            for chapter in mode.value:
                if not isinstance(chapter.value,list):continue
                chunk=text[chapter.key.start:entry_end(text,chapter)]
                maps=mission_maps(('"mission" { "modes" { "test" { '+chunk+' } } }').encode('utf8',errors='surrogateescape'))
                if not maps:continue
                absent=[n for n in maps if not available(n)]
                if absent:
                    if len(absent)!=len(maps):
                        raise ValueError('Cannot safely prune a chapter containing both available and missing maps')
                    local.append((chapter.key.start,entry_end(text,chapter)))
                    removed.append({'mode':mode.key.value,'maps':absent})
                else:kept+=1
            if local:
                edits.extend(local if kept else [(mode.key.start,entry_end(text,mode))])
    for start,end in sorted(edits,reverse=True):text=text[:start]+text[end:]
    encoding='utf8' if _is_utf8(data) else 'cp1252'
    result=text.encode(encoding,errors='surrogateescape')
    parse(decode_text(result))
    return result,removed


def _is_utf8(data):
    try:data.decode('utf-8-sig');return True
    except UnicodeDecodeError:return False


def repair_legacy_pistol_entities(data, available):
    """Resolve a missing historical pistol model per spawn type, not by shared alias."""
    changes=[]
    def entity(match):
        block=match.group(0)
        fields={m.group(1).lower():m.group(2).lower() for m in re.finditer(rb'"([^"\r\n]+)"\s*"([^"\r\n]*)"',block)}
        model=fields.get(b'model',b'').replace(b'\\',b'/')
        if model!=b'models/w_models/weapons/w_pistol_1911.mdl':return block
        kind=fields.get(b'classname',b'')
        if kind==b'weapon_pistol_spawn':target='models/w_models/weapons/w_pistol_a.mdl'
        elif kind==b'weapon_pistol_magnum_spawn' or (kind==b'weapon_spawn' and fields.get(b'weapon_selection')==b'weapon_pistol_magnum'):
            target='models/w_models/weapons/w_desert_eagle.mdl'
        else:return block
        if not available(target):return block
        pattern=rb'("model"\s*")[^"\r\n]*(")'
        out,count=re.subn(pattern,lambda m:m.group(1)+target.encode()+m.group(2),block,flags=re.I)
        if count!=1:return block
        changes.append({'classname':kind.decode(),'replacement':target,'hammerid':fields.get(b'hammerid',b'').decode(errors='replace')})
        return out
    return re.sub(rb'\{[^{}]*\}',entity,data),changes


def replace_entity_lump(data, entities):
    """Append a PC entity lump while preserving every other byte/lump."""
    from .formats import bsp_rows
    if data[:4]!=b'VBSP':raise ValueError('Compatibility entity repair expects PC BSP')
    rows=bsp_rows(data);version=struct.unpack_from('<I',data,4)[0]
    result=bytearray(data);result.extend(bytes((-len(result))%4));offset=len(result);result.extend(entities)
    row=(offset,len(entities),rows[0][2],0)
    if version==21:row=(row[2],row[0],row[1],row[3])
    struct.pack_into('<4I',result,8,*row)
    return bytes(result)


def remove_missing_relay_editor_icon(entities, present):
    """Strip only a missing editor icon from non-rendering logic_relay entities."""
    changes=[]
    def edit(match):
        block=match.group(0)
        pairs=dict((k.lower(),v.lower().replace(b'\\',b'/')) for k,v in re.findall(rb'"([^"\r\n]+)"\s*"([^"\r\n]*)"',block))
        icon=b'editor/new/logic_relay11.vmt'
        if pairs.get(b'classname')!=b'logic_relay' or pairs.get(b'model')!=icon or present('materials/'+icon.decode()):return block
        changed,count=re.subn(rb'"model"\s*"editor[/\\]new[/\\]logic_relay11\.vmt"',b'',block,flags=re.I)
        if count:changes.append({'action':'remove-missing-relay-editor-icon','material':'materials/'+icon.decode(),
            'reason':'Removed editor-only model key from a non-rendering logic_relay; outputs and other keys preserved.'})
        return changed
    return re.sub(rb'\{[^{}]*\}',edit,entities),changes


def apply_repairs(game, refs):
    game=Path(game);rows=[]
    files={p.relative_to(game).as_posix():p for p in game.rglob('*') if p.is_file()}
    maps=[n for n in files if n.endswith('.bsp')]
    if not maps:return rows  # Never trim standalone character/replacement addons.
    entities=b'\n'.join(bsp_lump(files[n].read_bytes(),0).lower() for n in maps)
    roots={n.decode('cp1252') for n in re.findall(rb'"(models/[^"\r\n]+\.mdl)"',entities)}
    for n in maps:roots.update(x.lower().replace('\\','/') for x in static_prop_summary(files[n].read_bytes())['models'])
    includes=set()
    for n,p in files.items():
        if n.endswith('.mdl'):
            try:includes.update(model_info(p.read_bytes())['includes'])
            except ValueError:pass  # Bad metadata must not enable trimming.
    dynamic=any(n.startswith('scripts/') or n.endswith(('.nut','.nuc','.lua','.cfg')) for n in files) or b'vscripts' in entities or b'"classname" "npc_' in entities
    for n in maps:
        pak=bsp_lump(files[n].read_bytes(),40)
        if pak and any(p.endswith(('.nut','.nuc','.lua','.cfg')) for p in XboxZip(pak).entries):dynamic=True
    if not dynamic:
        # Explicit legacy foreign-model families, not arbitrary unreferenced models.
        for stem in ('models/hair','models/zombie/fast','models/zombie/poison','models/player/zh/zh_zombie003'):
            name=stem+'.mdl'
            if name in roots|includes or name not in files:continue
            # Refuse to remove malformed models whose references cannot be proven.
            if any(n.endswith('.mdl') and _bad_model(p) for n,p in files.items()):break
            omitted=[]
            for n,p in list(files.items()):
                if n.startswith(stem+'.'):
                    omitted.append({'path':n,'sha256':digest(p.read_bytes())});p.unlink();del files[n]
            rows.append({'action':'omit-unreferenced-legacy-model','path':name,'files':omitted,
                'reason':'No map/model references found; no supplied scripts or entity vscripts. Limited to known legacy foreign model families.'})
    def available(stem):
        if 'maps/'+stem+'.bsp' in files:return True
        return any((refs.xbox_root/'left4dead2/maps'/(stem+ext)).is_file() for ext in ('.bsp','.360.bsp'))
    for n,p in files.items():
        if n.startswith('missions/') and n.endswith('.txt'):
            original=p.read_bytes()
            try:
                before,syntax_edits=repair_mission_mode_braces(original)
                after,removed=prune_mission(before,available)
            except ValueError as e:raise ValueError(f'{n}: {e}') from e
            if syntax_edits:
                p.write_bytes(before);rows.append({'action':'repair-mission-mode-closing-brace','path':n,
                    'edits':syntax_edits,'reason':'Inserted missing closing brace before an identifiable sibling game mode; validated the repaired tree.',
                    'before_sha256':digest(original),'after_sha256':digest(before)})
            if removed:
                p.write_bytes(after);rows.append({'action':'prune-missing-mission-maps','path':n,
                    'removed':removed,'before_sha256':digest(before),'after_sha256':digest(after)})
    def present(n):
        return n in files or n in refs.xbox or n in refs.supplemental_index or refs.pc_read(n) is not None
    def put(n,data,reason,origin):
        p=game/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);files[n]=p
        rows.append({'action':'compatibility-replacement','path':n,'reason':reason,'source':origin,'sha256':digest(data)})
    if not dynamic and not any(n.endswith('.mdl') and _bad_model(p) for n,p in files.items()):
        stems={n[:-4] for n in files if n.endswith(('.vvd','.phy'))}
        for stem in sorted(stems):
            if stem+'.mdl' in roots|includes or stem+'.mdl' in files:continue
            if present(stem+'.mdl'):
                # A same-name reference is not a recoverable parent when its
                # checksum differs from every supplied PC companion. Otherwise
                # preserve the files rather than guessing at a partial replacement.
                parent=refs.pc_read(stem+'.mdl')
                if not parent:continue
                try:checksum=model_info(parent)['checksum']
                except ValueError:continue
                checks=[]
                for ext in ('.vvd','.phy'):
                    companion=files.get(stem+ext)
                    if not companion:continue
                    b=companion.read_bytes();offset=8 if ext=='.vvd' else 12
                    if len(b)<offset+4 or (ext=='.vvd' and b[:4]!=b'IDSV'):
                        checks=[];break
                    checks.append(struct.unpack_from('<I',b,offset)[0])
                if not checks or checksum in checks:continue
            omitted=[]
            for n,p in list(files.items()):
                if n in {stem+'.vvd',stem+'.phy',stem+'.dx90.vtx',stem+'.dx80.vtx',stem+'.sw.vtx'}:
                    omitted.append({'path':n,'sha256':digest(p.read_bytes())});p.unlink();del files[n]
            if omitted:rows.append({'action':'omit-unreferenced-orphan-companions','path':stem+'.mdl','files':omitted,
                'reason':'No supplied parent model or map/model references; no supplied dynamic scripts. Any available PC parent has a different checksum from every supplied companion.'})
    pistol='models/w_models/weapons/w_pistol_1911'
    if not present(pistol+'.mdl'):
        for n in maps:
            p=files[n];before=p.read_bytes();original=bsp_lump(before,0)
            edited,changes=repair_legacy_pistol_entities(original,present)
            if changes:
                after=replace_entity_lump(before,edited);p.write_bytes(after)
                rows.append({'action':'repair-missing-weapon-spawn-models','path':n,'entities':changes,
                    'reason':'Missing historical pistol model resolved per actual weapon type; only entity model references change.',
                    'before_sha256':digest(before),'after_sha256':digest(after)})
    for n in maps:
        p=files[n];before=p.read_bytes()
        edited,changes=remove_missing_relay_editor_icon(bsp_lump(before,0),present)
        if changes:
            after=replace_entity_lump(before,edited);p.write_bytes(after)
            rows.append({'action':'remove-missing-relay-editor-icon','path':n,'entities':changes,
                'reason':'Missing authoring icon removed from non-rendering relay; relay behavior preserved.',
                'before_sha256':digest(before),'after_sha256':digest(after)})
    material_names={x.decode('cp1252').lower()+'.vmt' for n in maps for x in bsp_lump(files[n].read_bytes(),43).split(b'\0') if x}
    nodraw='materials/tf2m/materials/tools/toolsnodraw.vmt'
    if nodraw.removeprefix('materials/') in material_names and not present(nodraw):
        data=refs.pc_read('materials/tools/toolsnodraw.vmt')
        if data:put(nodraw,data,'Namespaced nodraw alias','User PC materials/tools/toolsnodraw.vmt')
    for trigger in ('hurt','once','multiple','teleport'):
        target='materials/tools/custom/trigger_'+trigger+'.vmt'
        if target.removeprefix('materials/') in material_names and not present(target):
            data=refs.pc_read('materials/tools/toolstrigger.vmt')
            if data and re.search(rb'["\s]%compiletrigger["\s]+["\s]*1',data,re.I):
                put(target,data,'Missing custom trigger material aliased to stock trigger; compiled brush geometry, contents and flags unchanged',
                    'User PC materials/tools/toolstrigger.vmt')
    common=files.get('scripts/vscripts/tumtara_common.nuc')
    if common is None and any(n.startswith('scripts/vscripts/tumtara_') for n in files) and getattr(refs,'library',None):
        common_data=refs.pc_read('scripts/vscripts/tumtara_common.nuc')
    else:common_data=common.read_bytes() if common else None
    helper='scripts/vscripts/cheats_off_message.nut'
    if common_data and not present(helper) and not present(helper[:-4]+'.nuc'):
        from .scripts import decode_script,literal_script_includes
        if 'cheats_off_message' in literal_script_includes(decode_script(common_data)):
            put(helper,b'function cheats_off_MSG() { printl("TUMTaRA: cheats are disabled; some test controls may not work."); }\n',
                'Absent Tumtara warning helper replaced with console warning only; does not enable cheats or alter map entities',
                'Independent compatibility script')
    laser='materials/sprites/bluelaser1.vmt'
    if b'sprites/bluelaser1.vmt' in entities and not present(laser):
        put(laser,b'"UnlitGeneric" { "$basetexture" "sprites/laserbeam" "$additive" "1" "$vertexcolor" "1" "$vertexalpha" "1" }\n',
            'Missing laser trail: stock laser texture with entity tint; appearance may differ','Independent material definition')
    bump='materials/realworldtextures/floor/mixtile/bump/512.vtf'
    if not present(bump) and any(b'realworldtextures/floor/mixtile/bump/512' in p.read_bytes().lower() for n,p in files.items() if n.endswith('.vmt')):
        data=refs.pc_read('materials/dev/flat_normal.vtf')
        if data:put(bump,data,'Missing floor normal: neutral normal fallback; surface bump detail lost','User PC materials/dev/flat_normal.vtf')
    return rows


def _bad_model(path):
    try:model_info(path.read_bytes());return False
    except ValueError:return True


def supplement_missing_materials(game, refs, missing):
    """Opt-in visible placeholders, never fabricated geometry or special shaders."""
    from .archive import safe_name
    game=Path(game);rows=[]
    texture='materials/dev/graygrid.vtf'
    if texture not in refs.xbox and refs.pc_read(texture) is None:return rows
    grouped={}
    for item in missing:
        name=safe_name(item['path'])
        grouped.setdefault(name,[]).append(item['owner'])
    for name,owners in sorted(grouped.items()):
        # A VMT can encode special effects/tool behavior; restrict supplementation
        # to missing materials explicitly referenced by model metadata.
        if not name.startswith('materials/') or not name.endswith('.vmt'):continue
        if not all(owner.endswith('.mdl') for owner in owners):continue
        path=game/name
        if path.exists():continue
        if name in refs.xbox or name in refs.supplemental_index or refs.pc_read(name) is not None:continue
        data=b'"VertexLitGeneric" { "$basetexture" "dev/graygrid" }\n'
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        rows.append({'action':'supplement-missing-model-material','path':name,'owners':owners,
            'replacement_texture':texture,'source':'Independent material definition; texture from user game reference',
            'reason':'Original model material is absent. Visible gray grid placeholder; original color, transparency and shader effects are not recovered.',
            'sha256':digest(data)})
    return rows

def recover_internal_material_aliases(game, refs, missing):
    """Opt-in recovery using the owning model's original internal directory."""
    from .archive import safe_name
    game=Path(game);rows=[];grouped={}
    for item in missing:grouped.setdefault(item['path'],[]).append(item['owner'])
    for name,owners in sorted(grouped.items()):
        if not name.startswith('materials/') or not name.endswith('.vmt') or not all(o.endswith('.mdl') for o in owners):continue
        candidates=set()
        for owner in owners:
            path=game/owner
            if not path.is_file():break
            data=path.read_bytes()
            try:
                model_info(data)
                internal=safe_name(data[12:76].split(b'\0')[0].decode('ascii')).removeprefix('models/')
            except (ValueError,UnicodeError):break
            parent=internal.rsplit('/',1)[0] if '/' in internal else ''
            if not parent:break
            candidates.add('materials/models/'+parent+'/'+name.rsplit('/',1)[-1])
        else:
            if len(candidates)!=1:continue
            candidate=candidates.pop()
            if candidate==name:continue
            source=game/candidate;data=source.read_bytes() if source.is_file() else refs.pc_read(candidate)
            if data is None:continue
            target=game/name
            if target.exists():continue
            parse(decode_text(data))
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            rows.append({'action':'recover-model-material-internal-directory','path':name,'source':candidate,'owners':owners,
                'reason':'Material alias recovered from the directory encoded in the original model name; material contents unchanged.',
                'sha256':digest(data)})
    return rows


def supplement_missing_textures(game,refs,missing):
    """Opt-in shader-role fallbacks, with lost appearance recorded explicitly."""
    from .dependencies import TEXTURES,reference_name
    from .keyvalues import leaf_pairs
    game=Path(game);rows=[];grouped={}
    for item in missing:grouped.setdefault(item['path'],[]).append(item['owner'])
    for name,owners in sorted(grouped.items()):
        if not name.startswith('materials/') or not name.endswith('.vtf') or not all(o.endswith('.vmt') for o in owners):continue
        if (game/name).exists() or name in refs.xbox or name in refs.supplemental_index or refs.pc_read(name) is not None:continue
        roles=set()
        for owner in owners:
            p=game/owner
            if not p.is_file():break
            try:
                tree=parse(decode_text(p.read_bytes()))
                # Unknown special-effect shaders must keep failing rather than
                # receive arbitrary albedo/normal substitutions.
                if len(tree)!=1 or tree[0].key.value.lower() not in ('vertexlitgeneric','lightmappedgeneric','unlitgeneric'):break
                local=set()
                for key,value in leaf_pairs(p.read_bytes()):
                    if key.lower() not in TEXTURES:continue
                    candidate=reference_name('materials/'+value.replace('\\','/').removesuffix('.vtf')+'.vtf','materials')
                    if candidate==name:local.add(key.lower())
                if not local:break
                roles.update(local)
            except ValueError:break
        else:
            if roles <= {'$bumpmap','$bumpmap2','$normalmap'}:
                origin='materials/dev/flat_normal.vtf';note='Neutral normal fallback; original bump detail is absent.'
                data=refs.pc_read(origin)
            elif roles <= {'$envmapmask','$selfillummask','$phongexponenttexture'} or (name=='materials/white.vtf' and roles <= {'$envmapmask','$selfillummask','$phongexponenttexture','$basetexture','$basetexture2','$detail'}):
                # Independent minimal PC VTF 7.2, opaque white RGBA8888.
                # This is a mask fallback, never a claim to recover the source.
                data=bytearray(84);data[:4]=b'VTF\0';struct.pack_into('<3I',data,4,7,2,80)
                struct.pack_into('<2H',data,16,1,1);struct.pack_into('<H',data,24,1)
                struct.pack_into('<I',data,52,0);data[56]=1;struct.pack_into('<I',data,57,0xffffffff)
                struct.pack_into('<H',data,63,1);data[80:]=bytes([255]*4);data=bytes(data)
                origin='Independent opaque white mask';note='White mask fallback; original mask pattern is absent.'
            elif roles <= {'$basetexture','$basetexture2','$detail'}:
                origin='materials/dev/graygrid.vtf';data=refs.pc_read(origin)
                note='Visible gray grid fallback; original color, transparency and detail are not recovered.'
            else:continue
            if data is None:continue
            p=game/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            rows.append({'action':'supplement-missing-texture','path':name,'owners':owners,'shader_roles':sorted(roles),
                'source':origin,'reason':note,'sha256':digest(data)})
    return rows


def retain_source_gaps(game,original_paths,missing):
    """Diagnostic-only retention of missing animation includes/textures.

    No geometry companions, map models or malformed files are waived. Kept
    references remain unresolved and must be shown prominently in the report.
    """
    game=Path(game);retained=[];required=[]
    for row in missing:
        owner=row['owner'];name=row['path'];eligible=False
        if owner in original_paths and owner.endswith('.mdl') and (game/owner).is_file():
            try:eligible=name in model_info((game/owner).read_bytes())['includes']
            except ValueError:pass
        if eligible:
            retained.append({**row,'reason':'Missing animation include already referenced by the supplied original model; kept unresolved for diagnostic testing. Animation or console stability may be affected.'})
        else:required.append(row)
    return required,retained
