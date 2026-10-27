"""Collect native L4D1 survivor dependencies from user-supplied Xbox DLC."""
from pathlib import Path
import hashlib,json,os,struct,threading,uuid
from .archive import XboxZip,aligned_zip,safe_name
from .formats import unpack_source,validate_asset
from .models import model_info,validate_bundle
from .native_materials import material_text
from .dependencies import canonical,TEXTURES,reference_name
from .keyvalues import leaf_pairs
from .loader_patcher import safe,emulator_running,has_loader
from .registration import merge_registered_addons,order_addon_baselines

NAME='Leave 2 Loader - L4D1 Survivors'
ROOTS=[f'models/survivors/survivor_{n}.mdl' for n in ('biker','manager','namvet','teenangst')]+[
    f'models/weapons/arms/v_arms_{n}.mdl' for n in ('francis','louis','bill','zoey')]
sha=lambda data:hashlib.sha256(data).hexdigest()

def collect_survivors(archives,progress=lambda _:None):
    index={};pools={}
    for path in archives:
        z=XboxZip(path)
        for n in z.entries:
            index[canonical(n)]=(z,n)
            if n.endswith('kvpool.360.image'):
                data=unpack_source(z.read(n));key=data[:4]
                if key in pools and pools[key]!=data:raise ValueError('Conflicting native material pool identity')
                pools[key]=data
    members={};records=[];seen=set();queue=[('model',n) for n in ROOTS]
    def read(name):
        row=index.get(canonical(name))
        return (row[0].read(row[1]),row) if row else (None,None)
    def add(name,required=True):
        data,row=read(name)
        if data is None:
            if required:raise ValueError('Survivor dependency missing from supplied DLC/game: '+name)
            return None
        z,actual=row
        if actual.endswith('.360.vtf'):validate_asset(actual,data)
        if actual not in members:
            members[actual]=data;records.append({'path':actual,'source':str(z.path),'source_sha256':sha(data)})
        return data
    while queue:
        kind,name=queue.pop(0);name=reference_name(name)
        if (kind,name) in seen:continue
        seen.add((kind,name));data=add(name)
        if kind=='model':
            progress('Collecting survivor model '+name)
            info=model_info(data)
            if info['endian']!='>':raise ValueError('Expected native Xbox survivor model: '+name)
            for ext in ('.vvd','.dx90.vtx','.phy'):add(name[:-4]+ext,False)
            if info['animation_file']:add(info['animation_file'])
            queue.extend(('model',n) for n in info['includes'])
            raw=unpack_source(data);nt,ti,nc,ci=struct.unpack_from('>4I',raw,204)
            if nt>1000 or nc>100 or ti+nt*64>len(raw) or ci+nc*4>len(raw):raise ValueError('Invalid survivor material table')
            def string(at):
                end=raw.find(b'\0',at)
                if not 0<=at<=end<len(raw):raise ValueError('Invalid survivor material string')
                return raw[at:end].decode('cp1252').lower().replace('\\','/')
            dirs=[string(struct.unpack_from('>I',raw,ci+j*4)[0]) for j in range(nc)] or ['']
            for j in range(nt):
                at=ti+j*64;texture=string(at+struct.unpack_from('>I',raw,at)[0])
                choices=[reference_name('materials/'+d+texture+'.vmt','materials') for d in dirs]
                selected=next((n for n in choices if n in index),None)
                if selected is None:raise ValueError('Native survivor material is missing: '+str(choices))
                queue.append(('material',selected))
        else:
            actual=index[canonical(name)][1];text=material_text(data,pools);members[actual]=text
            for key,value in leaf_pairs(text):
                key=key.lower();value=value.lower().replace('\\','/')
                if key=='include':queue.append(('material',reference_name(value)));continue
                if key in ('$fallbackmaterial','$crackmaterial'):
                    n=value if value.startswith('materials/') else 'materials/'+value
                    queue.append(('material',n if n.endswith('.vmt') else n+'.vmt'));continue
                if value in ('','0','1','none','env_cubemap') or value.startswith(('_rt_','$')):continue
                n=value if value.startswith('materials/') else 'materials/'+value
                try:n=reference_name(n if n.endswith('.vtf') else n+'.vtf','materials')
                except ValueError:
                    if key in TEXTURES:raise
                    continue
                if n in index:add(n)
                elif key in TEXTURES:raise ValueError('Native survivor texture is missing: '+n)
    for kind,name in seen:
        if kind=='model':validate_bundle(index[canonical(name)][1],members,console=True)
    return members,records

def complete_survivor_support(members,stock_archives,donor_archives):
    from .material_aliases import alias_material_tree
    from .survivor_arms import merge_arm_bindings
    # Use unique texture names as in the previously working lighting control;
    # retain the original shaders, proxies and IT/bile material distinctions.
    lookup={canonical(n):data for n,data in members.items()}
    roots=[n for n in members if n.endswith('.vmt')]
    aliased,alias_report=alias_material_tree(roots,lookup.get,'leave2/native_survivors')
    if any(aliased[new]!=lookup[old] for old,new in alias_report['texture_aliases'].items()):raise ValueError('Native texture alias changed its payload')
    result={n:data for n,data in members.items() if not n.endswith(('.vmt','.vtf'))}
    for name,data in aliased.items():result[name[:-4]+'.360.vtf' if name.endswith('.vtf') else name]=data
    stock={};donors={}
    for files,index in ((stock_archives,stock),(donor_archives,donors)):
        for path in files:
            z=XboxZip(path)
            for name in z.entries:
                if name.startswith('scripts/weapon_') and name.endswith('.txt'):index[name]=(z,name)
    arm_rows=[]
    for name,(z,key) in sorted(donors.items()):
        if name not in stock:continue # Do not introduce unrelated new weapons.
        base,original=stock[name];data,added=merge_arm_bindings(base.read(original),z.read(key))
        if added:
            result[name]=data;arm_rows.append({'path':name,'added':added,'source_weapon_settings_preserved':True})
    # Every added mapping must resolve to a bundled native arm model.
    for row in arm_rows:
        for entry in row['added']:
            if entry['model'][:-4]+'.360.mdl' not in result:raise ValueError('Arm binding references missing native model')
    return result,{'texture_aliases':alias_report,'weapon_arm_bindings':arm_rows,
        'native_texture_bytes_preserved':True,'native_models_unchanged':True,'pc_assets_used':False}

def prepare_support(game,source,tool,output,progress=lambda _:None,donor_archives=None):
    game=Path(game).resolve();output=Path(output).resolve();source=Path(source).resolve()
    if not (game/'default.xex').is_file():raise ValueError('Choose the extracted L4D2 game containing default.xex')
    if output.exists():raise ValueError('Survivor build output already exists')
    output.mkdir(parents=True)
    if donor_archives is not None:donors=[Path(p).resolve() for p in donor_archives]
    elif source.is_dir():donors=sorted(source.rglob('dlc*.zip'))
    elif source.suffix.lower()=='.zip':donors=[source]
    else:
        with source.open('rb') as f:
            magic=f.read(4);f.seek(0x360);title=f.read(4)
        if magic not in (b'LIVE',b'PIRS',b'CON ') or title!=bytes.fromhex('454108D4'):
            raise ValueError('Choose an L4D2 Xbox DLC package, or its extracted dlc.360.zip')
        from .containers import ContainerOptions,run
        extracted=output/'Extracted'
        run(ContainerOptions(str(tool),'Extract DLC',str(source),str(extracted)),
            lambda kind,value:progress(str(value)) if kind=='message' else None,threading.Event())
        donors=sorted(extracted.rglob('dlc*.zip'))
    if not donors:raise ValueError('No DLC asset archive found. Select The Sacrifice DLC containing all four L4D1 survivors.')
    def archive_order(p):
        import re
        m=re.match(r'zip(\d+)',p.name);return int(m[1]) if m else -1
    stock=sorted((game/'left4dead2').glob('zip*.zip'),key=archive_order)
    members,origins=collect_survivors([*stock,*donors],progress)
    members,compatibility=complete_survivor_support(members,stock,donors)
    addon=output/NAME;addon.mkdir()
    archive=aligned_zip(members);(addon/'zip0.360.zip').write_bytes(archive)
    check=XboxZip(addon/'zip0.360.zip')
    for n,data in members.items():
        if check.read(n)!=data:raise ValueError('Survivor archive readback mismatch')
    (addon/'addoninfo.txt').write_text('"AddonInfo"\n{\n "addontitle" "L4D1 Survivor Support"\n "addonversion" "1"\n "addonauthor" "Leave 2 Loader"\n "addondescription" "Native survivor bodies, arms, animations and materials extracted from your Xbox DLC. Keep enabled for campaigns using the L4D1 survivors."\n "leave2_managed" "1"\n "leave2_role" "base_resources"\n}\n',encoding='utf-8')
    receipt={'schema':1,'revision':2,'kind':'native-l4d1-survivors','source':str(source),'assets':origins,'asset_count':len(members),'compatibility':compatibility,
        'files':{p.name:sha(p.read_bytes()) for p in addon.iterdir()},'runtime_tested':False,
        'native_models_textures_preserved':True,'native_materials_decoded_to_text':True}
    (addon/'leave2-survivors.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    progress('Prepared native L4D1 support: '+str(len(members))+' assets.')
    return addon

def install_support(game,source,tool,workspace,progress=lambda _:None):
    if emulator_running():raise ValueError('Close Xenia normally before installing survivor support')
    game=Path(game).resolve();workspace=Path(workspace);workspace.mkdir(parents=True,exist_ok=True)
    if not has_loader(game):raise ValueError('Apply Leave 2 Loader before installing survivor support')
    target=safe(game,'left4dead2/addons/'+NAME)
    old_files=None
    if target.exists():
        receipt=target/'leave2-survivors.json'
        if not receipt.is_file():raise ValueError('Survivor support already exists without a verified receipt; preserve it before rebuilding')
        old_receipt=json.loads(receipt.read_text(encoding='utf-8'))
        files=old_receipt.get('files')
        if old_receipt.get('kind')!='native-l4d1-survivors' or not isinstance(files,dict) or old_receipt.get('revision',1)>=2:
            raise ValueError('Survivor support already exists; preserve or remove it before rebuilding')
        if {p.name for p in target.iterdir()}!=set(files)|{'leave2-survivors.json'}:
            raise ValueError('Survivor support contains extra user files; preserve it before rebuilding')
        old_files={}
        for name,digest in files.items():
            p=safe(target,name)
            if not p.is_file() or sha(p.read_bytes())!=digest:raise ValueError('Survivor support was modified; refusing to overwrite '+name)
            old_files[name]=digest
        old_files['leave2-survivors.json']=sha(receipt.read_bytes())
    staged=prepare_support(game,source,tool,workspace/('survivors-'+uuid.uuid4().hex),progress)
    # Register the support baseline before replacements, retaining every saved choice.
    state=safe(game,'left4dead2/addonlist.txt');before=state.read_bytes() if state.exists() else b''
    from .survivor_requirements import OFFLINE
    after,_=merge_registered_addons(before,[NAME]);after=order_addon_baselines(after,[OFFLINE,NAME])
    if emulator_running():raise ValueError('Close Xenia normally before installing survivor support')
    if (state.read_bytes() if state.exists() else b'')!=before:raise ValueError('Addon states changed during preparation; retry after closing the game')
    target.parent.mkdir(parents=True,exist_ok=True)
    import shutil
    temp=safe(game,'.leave2-loader/staging/survivors-'+uuid.uuid4().hex);temp.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(staged,temp)
    if old_files and any(sha(safe(target,name).read_bytes())!=digest for name,digest in old_files.items()):
        raise ValueError('Survivor support changed during preparation; no installed files changed')
    if before:
        backup=safe(game,'left4dead2/addonlist.txt.before-survivors-'+uuid.uuid4().hex);backup.write_bytes(before)
    else:backup=None
    addon_backup=None
    if old_files:
        addon_backup=safe(game,'.leave2-loader/backups/survivors-'+uuid.uuid4().hex)
        addon_backup.parent.mkdir(parents=True,exist_ok=True);os.replace(target,addon_backup)
    try:
        os.replace(temp,target)
        pending=state.with_name('addonlist.txt.survivors-'+uuid.uuid4().hex);pending.write_bytes(after);os.replace(pending,state)
    except Exception:
        # Target is the newly created, previously absent support folder only.
        if target.exists():shutil.rmtree(target)
        if addon_backup:os.replace(addon_backup,target)
        raise
    receipt=json.loads((target/'leave2-survivors.json').read_text())
    return {'status':'survivors-installed','folder':str(target),'backup':str(backup) if backup else None,
        'addon_backup':str(addon_backup) if addon_backup else None,'assets':receipt.get('asset_count',len(receipt['assets']))}
