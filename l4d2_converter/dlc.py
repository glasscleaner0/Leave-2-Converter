"""Build PC-owned official campaigns through the normal external-SDK pipeline."""
from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib
import json
import re
import shutil
import struct
import subprocess
import os
import tempfile
from . import __version__
from .archive import safe_name, aligned_zip, Vpk
from .core import Options, convert
from .dependencies import References
from .formats import bsp_lump
from .keyvalues import parse, Token, decode_text, mission_maps, mission_modes
from .loader import metadata_bytes
from .output import prepare_output
from .scripts import decode_script

CAMPAIGNS = {6:'The Passing',7:'The Sacrifice',8:'No Mercy',9:'Crash Course',
             10:'Death Toll',11:'Dead Air',12:'Blood Harvest',13:'Cold Stream'}
TITLES = {1:'Dead Center',2:'Dark Carnival',3:'Swamp Fever',4:'Hard Rain',5:'The Parish',**CAMPAIGNS}
PC_FOLDERS=('update','left4dead2_dlc3','left4dead2_dlc2','left4dead2_dlc1','left4dead2','hl2')

@dataclass
class DlcOptions:
    pc_game: str
    output: str
    sdk_bin: str
    xbox_game: str
    runtime_bin: str = ''
    audio_decoder: str = ''
    campaigns: tuple = tuple(CAMPAIGNS)
    timeout: int = 120
    overwrite: bool = False
    supplement_missing_materials: bool = False


def campaign_selection(values):
    values=tuple(values)
    if not values or len(set(values))!=len(values) or any(type(i) is not int or i not in CAMPAIGNS for i in values):
        raise ValueError('Select one or more supported campaigns (6 through 13), without duplicates')
    return tuple(i for i in CAMPAIGNS if i in values)


def campaign_mission(data, number):
    """Use an alphanumeric console mission ID while retaining original map transitions."""
    text=decode_text(data);root=parse(text)
    if len(root)!=1 or root[0].key.value.lower()!='mission' or not isinstance(root[0].value,list):raise ValueError('Invalid PC campaign mission')
    names=[e for e in root[0].value if e.key.value.lower()=='name' and isinstance(e.value,Token)]
    if len(names)!=1 or names[0].value.value.lower()!=f'l4d2c{number}':raise ValueError('PC mission identity differs from the selected campaign')
    maps=mission_maps(data)
    if not maps or any(not re.fullmatch(f'c{number}m[0-9]+_[a-z0-9_]+',m) for m in maps):raise ValueError('PC mission references maps outside the selected campaign')
    # Xbox MissionManager rejects underscores and other non-alphanumeric ID characters.
    value=names[0].value;text=text[:value.start]+'"l2pcc'+str(number)+'"'+text[value.end:]
    return text.encode('utf-8'),maps


def pc_asset(refs,name):
    # Loose update files take precedence over VPK content, matching PC search paths.
    name=safe_name(name)
    for folder in PC_FOLDERS:
        candidate=refs.pc_root/folder/name
        if candidate.is_file() and not candidate.is_symlink():return candidate.read_bytes(),str(candidate)
    data=refs.pc_read(name)
    return data,('vpk:'+name if data is not None else None)


def achievement_asset_names(refs, number):
    """Inventory the owning PC DLC's icons, resolving payloads via normal precedence."""
    folder = 'left4dead2_dlc1' if number == 6 else 'left4dead2_dlc3' if number == 13 else 'left4dead2_dlc2'
    base = refs.pc_root / folder
    prefix = 'materials/vgui/achievements/'
    names = set()
    for path in sorted(base.glob('*_dir.vpk')):
        archive = Vpk(path)
        names.update(n for n in archive.entries if n.startswith(prefix) and n.endswith(('.vmt', '.vtf')))
    loose = base / prefix
    if loose.is_dir():
        names.update(safe_name(p.relative_to(base).as_posix()) for p in loose.rglob('*')
                     if p.is_file() and not p.is_symlink() and p.suffix.lower() in ('.vmt', '.vtf'))
    return sorted(names)


def console_poster(data, decoder, workspace):
    """Resize oversized ordinary DXT posters using user-owned FFmpeg, preserving content."""
    if len(data)<80 or data[:4]!=b'VTF\0':return data,None
    width,height=struct.unpack_from('<2H',data,16)
    if max(width,height)<=1024:return data,None
    major,minor,header=struct.unpack_from('<3I',data,4);fmt=struct.unpack_from('<I',data,52)[0]
    flags=struct.unpack_from('<I',data,20)[0];frames=struct.unpack_from('<H',data,24)[0]
    if major!=7 or minor!=2 or fmt not in (13,15) or frames!=1 or flags&0x4000 or struct.unpack_from('<H',data,63)[0]!=1:
        raise ValueError('Unsupported oversized PC loading poster; cannot safely resize this VTF layout')
    if not decoder or not Path(decoder).is_file():raise ValueError('Oversized PC loading posters require FFmpeg; set its path on the Converter tab')
    block=8 if fmt==13 else 16;mips=data[56]
    if not 1<=mips<=max(width,height).bit_length():raise ValueError('Invalid loading-poster mip count')
    loww,lowh=data[61:63];lowfmt=struct.unpack_from('<I',data,57)[0]
    if loww and lowh and lowfmt!=13:raise ValueError('Unsupported loading-poster thumbnail')
    image=header+(((loww+3)//4)*((lowh+3)//4)*8 if loww and lowh else 0)
    small=sum(((max(1,width>>i)+3)//4)*((max(1,height>>i)+3)//4)*block for i in range(1,mips))
    size=((width+3)//4)*((height+3)//4)*block;payload=data[image+small:image+small+size]
    if len(payload)!=size:raise ValueError('Truncated loading-poster image')
    dds=bytearray(128);dds[:4]=b'DDS ';struct.pack_into('<7I',dds,4,124,0x81007,height,width,size,0,1)
    struct.pack_into('<2I',dds,76,32,4);dds[84:88]=b'DXT1' if fmt==13 else b'DXT5';struct.pack_into('<I',dds,108,0x1000)
    scale=min(512/width,512/height);w=max(4,int(width*scale)//4*4);h=max(4,int(height*scale)//4*4)
    with tempfile.TemporaryDirectory(prefix='.poster-',dir=workspace) as temporary:
        source=Path(temporary)/'poster.dds';source.write_bytes(bytes(dds)+payload)
        run=subprocess.run([str(decoder),'-v','error','-nostdin','-i',str(source),'-vf',f'scale={w}:{h}',
            '-frames:v','1','-f','rawvideo','-pix_fmt','rgba','pipe:1'],capture_output=True,timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if run.returncode or len(run.stdout)!=w*h*4:raise ValueError('Loading-poster resizing failed: '+run.stderr.decode(errors='replace')[-300:])
    from .loader import rgba_vtf
    header=bytearray(rgba_vtf(bytes(w*w*4),size=w)[:80]);struct.pack_into('<2H',header,16,w,h)
    return bytes(header)+run.stdout,{'method':'poster-resize-with-ffmpeg','before':[width,height],'after':[w,h],
        'reason':'Oversized PC loading poster rejected by external SDK; visual resolution reduced, full image retained'}


def stage_campaign(refs,number,destination,cancelled=lambda:False,decoder='',supplement=False):
    """Collect scoped map files and dynamic dependencies, leaving PC files untouched."""
    destination=Path(destination);destination.mkdir(parents=True)
    data,origin=pc_asset(refs,f'missions/campaign{number}.txt')
    if data is None:raise ValueError('PC campaign mission is missing: '+str(number))
    mission,maps=campaign_mission(data,number)
    manifest=[];warnings=[];scripts=[];seen=set();entities=[];overlays=[];repairs=[]
    def put(name,data,origin):
        if cancelled():raise InterruptedError('DLC conversion cancelled')
        name=safe_name(name)
        if name in seen:return
        if name.startswith('materials/vgui/loadingscreen') and name.endswith('.vtf'):
            data,repair=console_poster(data,decoder,destination.parent)
            if repair:repairs.append(dict(repair,path=name))
        seen.add(name);p=destination/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        manifest.append({'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'source':origin})
        if name.endswith(('.nut','.nuc')):scripts.append((name,data))
    put(f'missions/l2pcc{number}.txt',mission,origin)
    put('addoninfo.txt',metadata_bytes({'addontitle':CAMPAIGNS[number]+' (PC Port)','addonauthor':'Valve','leave2_role':'campaign_base',
        'addondescription':'Converted from your local PC installation. Experimental console port.'},'',False),'generated')
    for stem in maps:
        for extension in ('.bsp','.nav'):
            name='maps/'+stem+extension;payload,source=pc_asset(refs,name)
            if payload is None:raise ValueError('Required PC map file is missing: '+name)
            put(name,payload,source)
            if extension=='.bsp':entities.append((name,bsp_lump(payload,0)))
        for folder in PC_FOLDERS:
            for p in (refs.pc_root/folder/'maps').glob(stem+'*.lmp'):
                overlays.append({'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'status':'not-applied'})
    # Do not feed PC entity overlays directly to the Xbox loader. Their format and
    # mode/violence selection differ. Base BSP entity data is explicitly retained.
    if overlays:warnings.append('PC external entity .lmp overlays are not applied in this first version; base compiled BSP entities are used. Later PC map fixes/easter eggs may differ.')
    prefix=re.compile(rf'^(?:maps/c{number}m\d+_|scripts/vscripts/c{number}m\d+_)')
    names=set(refs.pc)
    for folder in PC_FOLDERS:
        for sub in ('maps','scripts/vscripts'):
            directory=refs.pc_root/folder/sub
            if directory.is_dir():names.update(safe_name(p.relative_to(refs.pc_root/folder).as_posix()) for p in directory.glob(f'c{number}m*') if p.is_file())
    for name in sorted(names):
        if prefix.match(name) and name.endswith(('.nut','.nuc','.txt','.vmt','.vtf')) and not name.endswith('_commentary.txt'):
            payload,source=pc_asset(refs,name)
            if payload is not None:put(name,payload,source)
    # Explicit script references and include chains are not covered by static BSP geometry scans.
    def script(identifier,owner):
        identifier=identifier.replace('\\','/').strip().removeprefix('scripts/vscripts/')
        stem=re.sub(r'\.(nut|nuc)$','',identifier,flags=re.I)
        for ext in ('.nut','.nuc'):
            name=safe_name('scripts/vscripts/'+stem+ext);payload,source=pc_asset(refs,name)
            if payload is not None:put(name,payload,source);return
        warnings.append('Unresolved dynamic script '+identifier+' referenced by '+owner)
    for owner,entity in entities:
        for value in re.findall(rb'"vscripts"\s*"([^"\r\n]+)"',entity,re.I):
            for item in decode_text(value).split():script(item,owner)
    index=0
    while index<len(scripts):
        owner,payload=scripts[index];index+=1
        text=decode_text(decode_script(payload) if owner.endswith('.nuc') else payload)
        for include in re.findall(r'(?:IncludeScript|DoIncludeScript)\s*\(\s*["\']([^"\']+)["\']',text):script(include,owner)
        for model in re.findall(r'["\'](models/[^"\'\r\n]+\.mdl)["\']',text,re.I):
            if model.lower() not in refs.xbox:
                payload,source=pc_asset(refs,model)
                if payload is not None:put(model,payload,source)
    # L4D1 survivors and infected arms are selected at runtime by mission metadata.
    if number in range(7,13):
        for character in ('biker','manager','namvet','teenangst'):
            name=f'models/survivors/survivor_{character}.mdl'
            if name not in refs.xbox:
                payload,source=pc_asset(refs,name)
                if payload is not None:put(name,payload,source)
            light=f'models/survivors/survivor_{character}_light.mdl'
            if light not in refs.xbox:
                payload,source=pc_asset(refs,light)
                if payload is not None:put(light,payload,source)
    for key,value in re.findall(r'"([^"\r\n]+)"\s*"([^"\r\n]*)"',decode_text(mission)):
        value=value.replace('\\','/').lower()
        if value.startswith('models/') and value.endswith('.mdl') and value not in refs.xbox:
            payload,source=pc_asset(refs,value)
            if payload is not None:put(value,payload,source)
        if key.lower() in ('image','posterimage','posterimage_widescreen','outtroimage'):
            stem=value.removeprefix('vgui/')
            for ext in ('.vmt','.vtf'):
                name='materials/vgui/'+stem+ext;payload,source=pc_asset(refs,name)
                if payload is not None:put(name,payload,source)
    # Achievement menus load these dynamically; map and mission scans do not name them.
    achievement_assets = achievement_asset_names(refs, number)
    for name in achievement_assets:
        payload, source = pc_asset(refs, name)
        if payload is None:raise ValueError('PC DLC achievement asset is missing: ' + name)
        put(name, payload, source)
    # Hydrate dependencies before applying narrowly scoped legacy material repairs.
    from .dependencies import discover
    from .compatibility import apply_repairs,recover_internal_material_aliases
    from .dlc_repairs import repair_melee_placeholders,ascii_material_paths
    repairs.extend(repair_melee_placeholders(destination))
    repairs.extend(apply_repairs(destination,refs))
    discovery=discover(destination,refs)
    repairs.extend(recover_internal_material_aliases(destination,refs,discovery['missing']))
    # A uniquely named PC material can be recovered at an obsolete model search
    # path without changing its contents. Ambiguous names remain unresolved.
    for missing in discovery['missing']:
        name=missing['path']
        if not name.endswith('.vmt') or not missing['owner'].endswith('.mdl') or (destination/name).exists():continue
        basename=Path(name).name
        matches=[n for n in refs.pc if n.startswith('materials/') and Path(n).name==basename]
        if len(matches)==1:
            payload,origin=pc_asset(refs,matches[0])
            if payload is not None:
                put(name,payload,origin);repairs.append({'path':name,'method':'unique-model-material-alias','source':matches[0],
                    'sha256':hashlib.sha256(payload).hexdigest(),'reason':'Exactly one PC model material has the requested filename; bytes unchanged'})
    for p in (destination/'materials').rglob('*.vmt'):
        name=p.relative_to(destination).as_posix()
        if not p.is_file():continue
        text=decode_text(p.read_bytes())
        if not re.match(r'\s*"?water"?\s*\{',text,re.I):continue
        # These old Water materials have a missing DX8 dudv bump map, while the
        # actual DX9 normal map is present. Keep the normal map and water shader.
        missing='materials/nature/water_frame01_dudv.vtf'
        if refs.pc_read(missing) is not None or missing in refs.xbox:continue
        if refs.pc_read('materials/nature/water_frame01_normal.vtf') is None:continue
        fixed,count=re.subn(r'(?im)^\s*"?\$bumpmap"?\s+"?nature/water_frame01_dudv"?[^\r\n]*','',text)
        if count:
            p.write_text(fixed,encoding='utf-8');repairs.append({'path':name,'method':'remove-missing-legacy-water-dudv','reason':'Retain DX9 normal map; remove obsolete missing DX8 bump reference'})
    if supplement:
        for name,candidate in (('materials/sprites/whitepuff.vmt','materials/particle/particle_smokegrenade.vmt'),
                               ('materials/sprites/firetrail.vmt','materials/particle/fire_particle_3/fire_particle_3.vmt')):
            if any(row['path']==name for row in discovery['missing']) and refs.pc_read(name) is None:
                payload,origin=pc_asset(refs,candidate)
                if payload is not None:
                    put(name,payload,origin);repairs.append({'path':name,'method':'optional-stock-particle-material',
                        'source':candidate,'reason':'Source sprite is absent; use a smoke/fire material from the PC game. Appearance differs.'})
    repairs.extend(ascii_material_paths(destination))
    golden=[]
    for owner,entity in entities:
        golden.extend({'map':owner,'reference':decode_text(value)} for value in re.findall(rb'"([^"\r\n]*gold[^"\r\n]*crowbar[^"\r\n]*)"',entity,re.I))
    return {'campaign':number,'title':CAMPAIGNS[number],'mission':'l2pcc'+str(number),'maps':maps,
        'modes':mission_modes(mission),'files':manifest,'warnings':warnings,'pc_entity_overlays':overlays,'golden_crowbar_references':golden,'staging_repairs':repairs,'achievement_assets':achievement_assets}


def menu_resources(refs,ready):
    """Regenerate standard menu rows; converted IDs route to custom mission identities."""
    if not ready:return {}
    result={}
    order=[1,6,2,3,4,5,7,8,9,10,11,12,13]
    for mode,suffix in (('coop',''),('versus','versus'),('survival','survival'),('scavenge','scavenge')):
        for extended in (False,True):
            name='resource/ui/l4d360ui/dropdownmission'+suffix+('extended' if extended else '')+'.res'
            # Read template from the user's console files, never bundled Valve resources.
            control='L4D360HybridButton'
            # Some stock mode resources inherit the coop dropdown through #base.
            # Validate that bounded inheritance rather than rejecting the stub.
            current=name;visited=set()
            for _ in range(8):
                if current in visited:raise ValueError('Campaign menu inheritance cycle: '+name)
                visited.add(current);template=refs.xbox_read(current)
                if control.encode() in template:break
                inherited=re.fullmatch(rb'\s*#base\s+"([A-Za-z0-9_./-]+\.res)"\s*',template)
                if not inherited:raise ValueError('Unrecognized Xbox campaign menu template: '+name)
                parent=inherited[1].decode('ascii')
                current=safe_name(parent if parent.startswith('resource/') else current.rsplit('/',1)[0]+'/'+parent)
            else:raise ValueError('Campaign menu inheritance depth exceeded: '+name)
            rows=[]
            for i in order:
                # Imported campaigns without maps for this mode must not fall
                # back to their unavailable stock DLC identity.
                if i in ready and mode not in ready[i]['modes']:continue
                selected=i in ready and mode in ready[i]['modes']
                identifier='l2pcc'+str(i) if selected else 'L4D2C'+str(i)
                label=TITLES[i] if selected or i<6 else TITLES[i]+' (DLC)'
                rows.append(('BtnCampaign'+str(i),label,'cmd_campaign_'+identifier))
            if extended:rows.append(('BtnAny','Any Campaign','cmd_campaign_'))
            rows.append(('BtnCampaignCustom','Addon campaigns...','cmd_addoncampaign'))
            def scalar(k,v):return f'"{k}" "{v}"\n'
            text='"'+name+'"\n{\n"FlyoutMenuSettings" { "noblindnavigation" "1" }\n'
            text+='"PnlBackground" { "ControlName" "Panel" "fieldName" "PnlBackground" "xpos" "0" "ypos" "0" "zpos" "-1" "wide" "180" "tall" "'+str(len(rows)*20+5)+'" "visible" "1" "enabled" "1" "paintbackground" "1" }\n'
            for index,(field,label,command) in enumerate(rows):
                values={'ControlName':control,'fieldName':field,'xpos':'0','ypos':str(index*20),'wide':'174','tall':'20',
                    'visible':'1','enabled':'1','tabPosition':'0','wrap':'1','navUp':rows[index-1][0],
                    'navDown':rows[(index+1)%len(rows)][0],'labelText':label,'style':'FlyoutMenuButton','command':command}
                text+='"'+field+'"\n{\n'+''.join(scalar(k,v) for k,v in values.items())+'}\n'
            text+='}\n';parse(text);result[name]=text.encode('utf-8')
            # The installed campaign browser redirects dropdowns to addonbase_ resources.
            alias=name.replace('/dropdownmission','/addonbase_dropdownmission')
            result[alias]=text.replace(name,alias,1).encode('utf-8')
    return result



def build_population_runtime(refs,ready,options,output,install,progress=print,cancelled=lambda:False):
    """Publish one shared population owner for the union of successful campaigns."""
    from .populations import stage_populations
    navs={}
    for staged in ready.values():
        for stem in staged['maps']:
            name='maps/'+stem+'.nav';data,_=pc_asset(refs,name)
            if data is None:raise ValueError('Required population NAV missing: '+name)
            navs[name]=data
    source=output/'Population-Runtime-Source'
    discovery=stage_populations(refs,navs,source)
    (source/'addoninfo.txt').write_bytes(metadata_bytes({'addontitle':'PC Campaign Runtime','addonauthor':'Leave 2 Converter','leave2_role':'base_resources',
        'addondescription':'Shared infected populations and models for the converted PC campaigns. Keep enabled with the campaign ports.'},'',False))
    build=output/'Population-Runtime-Build'
    result=convert(Options(input=str(source),output=str(build),sdk_bin=options.sdk_bin,xbox_game=options.xbox_game,
        pc_game=options.pc_game,runtime_bin=options.runtime_bin,audio_decoder=options.audio_decoder,
        timeout=options.timeout,leave2_loader=True),progress=lambda s:progress('Campaign runtime: '+s),cancelled=cancelled)
    if result['status']!='converted-awaiting-console-test':
        raise ValueError('Campaign population/model conversion failed; see '+str(build/'report.json'))
    folder=build/result['leave2_loader']['folder'];target=install/folder.name
    shutil.copytree(folder,target)
    return {'folder':str(target.relative_to(output)),'report':str(build/'report.json'),'discovery':discovery,'runtime_tested':False}


def convert_dlc(options,progress=print,cancelled=lambda:False):
    chosen=campaign_selection(options.campaigns)
    pc=Path(options.pc_game).resolve()
    if not (pc/'left4dead2').is_dir():raise ValueError('Choose the PC Left 4 Dead 2 installation, containing left4dead2')
    output,backup=prepare_output(options)
    report={'version':__version__,'options':asdict(options),'status':'running','jobs':[],'failures':[],
        'campaigns':[],'hardware_tested':False,'previous_output_backup':str(backup) if backup else None}
    def save():(output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    save();ready={};install=output/'Addons';install.mkdir()
    try:
        progress('Indexing the PC install and console base-game references...')
        refs=References(options.xbox_game,str(pc))
        for number in chosen:
            if cancelled():raise InterruptedError('DLC conversion cancelled')
            title=CAMPAIGNS[number];progress('Preparing '+title+'...');entry={'campaign':number,'title':title,'status':'running'};report['campaigns'].append(entry);save()
            try:
                source=output/'Sources'/f'c{number}'
                staged=stage_campaign(refs,number,source,cancelled,options.audio_decoder,options.supplement_missing_materials)
                entry['source']=staged;save()
                build=output/'Builds'/f'c{number}'
                result=convert(Options(input=str(source),output=str(build),sdk_bin=options.sdk_bin,xbox_game=options.xbox_game,
                    pc_game=str(pc),runtime_bin=options.runtime_bin,audio_decoder=options.audio_decoder,timeout=options.timeout,
                    leave2_loader=True,resource_list_mode='per-map',force_supplemented_resources=options.supplement_missing_materials),progress=lambda s:progress(title+': '+s),cancelled=cancelled)
                entry.update(status=result['status'],report=str(build/'report.json'),failures=result.get('failures',[]),supplemented_resources=result.get('supplemented_resources',[]))
                if result['status']=='converted-awaiting-console-test':
                    folder=build/result['leave2_loader']['folder'];target=install/folder.name
                    pending=output/'Publishing'/folder.name
                    if not pending.resolve().is_relative_to(output.resolve()) or not target.resolve().is_relative_to(output.resolve()):
                        raise ValueError('Addon publication path escapes the selected output')
                    pending.parent.mkdir(exist_ok=True);shutil.copytree(folder,pending);pending.rename(target)
                    entry['addon_folder']=str(target.relative_to(output));ready[number]=staged
                else:report['failures'].append({'campaign':number,'reason':result.get('error') or 'Conversion has unresolved failures; see campaign report'})
            except InterruptedError:raise
            except Exception as error:
                progress(title+': '+str(error))
                entry.update(status='failed',error=str(error));report['failures'].append({'campaign':number,'reason':str(error)})
            save()
        if ready:
            try:
                progress('Building shared NAV-selected infected populations and models...')
                report['population_runtime']=build_population_runtime(refs,ready,options,output,install,progress,cancelled)
            except InterruptedError:raise
            except Exception as error:
                report['failures'].append({'component':'population-runtime','reason':str(error)})
                progress('Shared campaign runtime failed: '+str(error))
            save()
            menu=output/'Publishing/PC Campaign Menu';menu.mkdir(parents=True)
            resources=menu_resources(refs,ready)
            (menu/'zip0.360.zip').write_bytes(aligned_zip(resources))
            (menu/'addoninfo.txt').write_bytes(metadata_bytes({'addontitle':'PC Campaign Menu','addonauthor':'Leave 2 Converter',
                'addondescription':'Routes the original campaign buttons to locally converted PC campaigns. Keep enabled with the matching campaign folders.'},'',False))
            menu.rename(install/menu.name)
            report['menu']={'folder':'Addons/PC Campaign Menu','campaigns':sorted(ready),'files':sorted(resources),'runtime_tested':False}
        report['status']='converted-awaiting-console-test' if not report['failures'] else 'partial' if ready else 'failed'
    except InterruptedError as error:report.update(status='cancelled',error=str(error))
    except Exception as error:report.update(status='failed',error=str(error))
    finally:
        (output/'INSTALL.txt').write_text('PC DLC campaign ports (experimental)\n\nCopy the folders inside Addons/ into left4dead2/addons/ in your Leave 2 Loader game.\nKeep PC Campaign Menu and PC Campaign Runtime enabled along with the matching campaign folders. Fully restart.\nThe standard campaign buttons route to custom mission IDs with original map names.\nUse only one active copy of each campaign. Official DLC and other map replacements may conflict.\nNo console package licenses, game binaries, addonlist states or source PC files were modified.\nPC external entity overlays are reported but not applied. Runtime feature, memory,\nsound and scripted-event compatibility require testing. The Last Stand is excluded.\nFailed campaigns are not installed or added to the menu; inspect report.json and Builds/.\nKeep existing addons and save states. Remove these new folders to undo this installation.\n',encoding='utf-8')
        save()
    return report
