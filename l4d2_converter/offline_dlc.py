"""Repackage user-owned native Xbox DLC without PC asset conversion."""
from pathlib import Path
import hashlib,json,os,re,shutil,threading
from .archive import XboxZip,aligned_zip
from .containers import ContainerOptions,run
from .dependencies import References
from .dlc import CAMPAIGNS,campaign_mission,menu_resources
from .formats import bsp_rows,bsp_lump
from .keyvalues import prepare_mission,mission_modes,parse,decode_text,Token,tokens
from .loader_patcher import has_loader
from .survivor_requirements import requires_l4d1,CREW,NOTE,require_crew_enabled

NAME='Offline Xbox DLC'
def native_offline_mission(data):
    """Keep the original map-lookup identity, clearing only its offline DLC flags."""
    text=decode_text(data);tree=parse(text)
    if len(tree)!=1 or not isinstance(tree[0].value,list):raise ValueError('Expected native mission definition')
    values={'dlcmask':'0x0000000000000000','dlcrequired':'0'};edits=[];found=set()
    for e in tree[0].value:
        key=e.key.value.lower()
        if key in values:
            if key in found or not isinstance(e.value,Token):raise ValueError('Invalid or duplicate native DLC mission flag')
            found.add(key);edits.append((e.value.start,e.value.end,'"'+values[key]+'"'))
    missing=''.join('\n\t"'+key+'" "'+value+'"' for key,value in values.items() if key not in found)
    if missing:
        opening=next(t for t in tokens(text) if t.kind=='brace' and t.value=='{')
        edits.append((opening.end,opening.end,missing+'\n'))
    for start,end,value in sorted(edits,reverse=True):text=text[:start]+value+text[end:]
    result=text.encode('utf-8');parse(text);return result

def digest_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def build_offline_dlc(game,sources,output,tool,progress=lambda _:None,stop=None,*,pc_preview_options=None):
    stop=stop or threading.Event();game=Path(game).resolve();output=Path(output).resolve()
    if not sources:raise ValueError('Choose one or more Xbox DLC packages or extracted DLC folders')
    if not (game/'default.xex').is_file() or not has_loader(game):
        raise ValueError('Choose a game already patched with Leave 2 Loader')
    if output.exists():raise ValueError('Choose a new output folder; existing outputs are preserved')
    sources=[Path(p).resolve() for p in sources]
    if len(set(sources))!=len(sources):raise ValueError('Duplicate DLC source')
    if any(output==p or output.is_relative_to(p) for p in sources if p.is_dir()):raise ValueError('Output must be outside source folders')
    output.mkdir(parents=True);work=output/'.work';work.mkdir();stage=work/NAME;stage.mkdir()
    report={'status':'preparing','sources':[str(p) for p in sources],'archives':[],'maps':[],'campaigns':{},'pc_conversion_used':False,
        'game_files_modified':False,'profile_or_license_files_modified':False,'runtime_tested':False}
    def check():
        if stop.is_set():raise InterruptedError('Offline DLC build cancelled')
    try:
        donors=[]
        for i,source in enumerate(sources):
            check()
            if source.is_dir():extracted=source
            elif source.suffix.lower()=='.zip':extracted=source.parent
            else:
                with source.open('rb') as f:magic=f.read(4);f.seek(0x360);title=f.read(4)
                if magic not in (b'LIVE',b'PIRS',b'CON ') or title!=bytes.fromhex('454108D4'):
                    raise ValueError('Not an L4D2 Xbox DLC package: '+str(source))
                extracted=work/('package-'+str(i));progress('Extracting Xbox DLC package '+source.name)
                result=run(ContainerOptions(str(tool),'Extract DLC',str(source),str(extracted)),
                    lambda kind,value:progress(str(value)) if kind=='message' else None,stop)
                if result['status']!='complete':raise InterruptedError('DLC extraction cancelled')
            paths=[source] if source.is_file() and source.suffix.lower()=='.zip' else sorted(extracted.rglob('dlc*.zip'))
            for path in paths:
                if re.fullmatch(r'left4dead2_dlc[123]',path.parent.name.lower()):donors.append(path)
            if not paths:raise ValueError('No native DLC archive found in '+str(source))
        if not donors:raise ValueError('No English left4dead2_dlc1, dlc2 or dlc3 folders found')
        # Native pools/preloads are intentionally kept in their original archives.
        # This mirrors the working original-Xbox No Mercy control.
        seen_roles={};index={};loose={}
        for path in sorted(donors,key=lambda p:p.parent.name):
            check();role=path.parent.name.lower();digest=digest_file(path)
            if role in seen_roles:
                if seen_roles[role]!=digest:raise ValueError('Two different DLC archives supplied for '+role)
                continue
            seen_roles[role]=digest;z=XboxZip(path)
            destination=stage/('zip'+str(len(report['archives']))+'.360.zip')
            progress('Copying native '+role+' assets…');shutil.copyfile(path,destination)
            if digest_file(destination)!=digest:raise ValueError('Native DLC copy verification failed')
            report['archives'].append({'file':destination.name,'role':role,'bytes':destination.stat().st_size,'sha256':digest,'source':str(path)})
            for name in z.entries:index[name]=(z,name)
            maps=path.parent/'maps'
            if maps.is_dir():
                for p in sorted(maps.rglob('*')):
                    check()
                    if not p.is_file():continue
                    if p.is_symlink():raise ValueError('Linked DLC map files are unsupported')
                    name='maps/'+p.relative_to(maps).as_posix().lower()
                    if name in loose and digest_file(loose[name])!=digest_file(p):raise ValueError('Conflicting native map '+name)
                    loose[name]=p
        refs=References(game);ready={};mission_files={};crew_required=False
        for number,title in CAMPAIGNS.items():
            check();mission_key=f'missions/campaign{number}.txt'
            if mission_key not in refs.xbox:continue
            original=refs.xbox_read(mission_key)
            _,prepared=prepare_mission(original);mission,maps=campaign_mission(prepared,number)
            if not all('maps/'+m+'.360.bsp' in loose or 'maps/'+m+'.360.bsp' in index for m in maps):continue
            for stem in maps:
                key='maps/'+stem+'.360.bsp'
                data=loose[key].read_bytes() if key in loose else index[key][0].read(key)
                bsp_rows(data);XboxZip(bsp_lump(data,40))
                nav='maps/'+stem+'.360.nav'
                if nav not in index and nav not in loose:raise ValueError('Native DLC navigation missing: '+nav)
            ready[number]={'modes':mission_modes(mission),'mission':'l2pcc'+str(number)}
            # Final server-info validation performs its own map-to-mission lookup
            # and can select L4D2C8 even after the UI selected l2pcc8.
            mission_files[mission_key]=native_offline_mission(original)
            mission_files[f'missions/l2pcc{number}.txt']=mission
            report['campaigns'][str(number)]={'title':title,'mission':'l2pcc'+str(number),'maps':maps,'modes':ready[number]['modes']}
            crew_required=crew_required or requires_l4d1(mission)
        if not ready:raise ValueError('No complete native DLC campaigns found; include their loose maps and the matching integrated title update')
        for name,source in loose.items():
            check();dest=stage/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
            a=digest_file(source);b=digest_file(dest)
            if a!=b:raise ValueError('Native map copy verification failed')
            report['maps'].append({'path':name,'sha256':a,'bytes':dest.stat().st_size})
        additions={**menu_resources(refs,ready),**mission_files}
        from .native_dlc_visuals import collect_visual_support,startup_visual_members
        progress('Preparing native DLC icons, chapter previews and minigun materials…')
        stock_archives=list({str(z.path):z for z,_ in refs.xbox.values()}.values())
        visuals,report['native_visual_support']=collect_visual_support(sorted(donors,key=lambda p:p.parent.name),
            stock_archives=stock_archives,missions=[mission_files[f'missions/campaign{number}.txt'] for number in ready])
        missing_previews=report['native_visual_support']['chapter_preview_fallbacks']
        if missing_previews and pc_preview_options:
            from .pc_chapter_previews import convert_pc_previews
            textures,report['pc_chapter_previews']=convert_pc_previews(
                [r['material'] for r in missing_previews],work=work/'PC-Previews',progress=progress,
                cancelled=stop.is_set,**pc_preview_options)
            visuals,report['native_visual_support']=collect_visual_support(sorted(donors,key=lambda p:p.parent.name),
                stock_archives=stock_archives,missions=[mission_files[f'missions/campaign{number}.txt'] for number in ready],preview_textures=textures)
            report['pc_conversion_used']=True
        additions.update(visuals)
        # Also publish loose mission definitions, matching the established Loader layout.
        for name,data in mission_files.items():p=stage/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        final=stage/('zip'+str(len(report['archives']))+'.360.zip');payload=aligned_zip(additions);final.write_bytes(payload)
        z=XboxZip(final)
        if any(z.read(n)!=d for n,d in additions.items()):raise ValueError('Offline DLC menu/mission archive readback failed')
        (stage/'addoninfo.txt').write_text('"AddonInfo"\n{\n "addontitle" "Offline Xbox DLC"\n "addonversion" "1"\n "addonauthor" "Valve; local packaging by Leave 2 Loader"\n "addondescription" "Native Xbox DLC campaigns and support assets from your own packages."\n "leave2_managed" "1"\n "leave2_role" "campaign_base"\n}\n',encoding='utf-8')
        crew_stage=None
        if crew_required:
            check();progress('Building required L4D1 crew companion…')
            from .survivor_support import prepare_support
            crew_stage=prepare_support(game,donors[0].parent,tool,work/'Crew-Support',progress,donor_archives=sorted(donors,key=lambda p:p.parent.name))
            receipt=json.loads((crew_stage/'leave2-survivors.json').read_text(encoding='utf-8'))
            report['required_survivor_support']={'folder':CREW,'revision':receipt['revision'],
                'files':{p.name:digest_file(p) for p in crew_stage.iterdir() if p.is_file()},'load_after':NAME,'note':NOTE}
            info=stage/'addoninfo.txt';text=info.read_text();info.write_text(text.rsplit('}',1)[0]+' "leave2_requires_l4d1_survivors" "1"\n}\n',encoding='utf-8')
        # Dialogue scenes/sound registration must be visible during startup,
        # before managed addons mount. Native audio stays in the DLC archives.
        from .startup_audio import export_startup_audio
        progress('Preparing native dialogue registration for game startup…')
        report['startup_audio']=export_startup_audio(game,sorted(donors,key=lambda p:p.parent.name),output/'Startup-Audio',startup_members=startup_visual_members(visuals))
        report['status']='built-awaiting-console-test';report['menu_mission_archive']={'file':final.name,'sha256':digest_file(final)}
        report['mission_policy']='Custom dropdown identities plus original map-lookup mission overrides with zero DLC flags, scoped to imported campaigns; native BSP names and transitions unchanged.'
        report['original_mission_overrides']=[f'missions/campaign{number}.txt' for number in ready]
        report['registration_conflicts']='Disable matching PC campaign ports, PC Campaign Menu and PC Campaign Runtime when testing this native package.'
        report['generated_files']={p.relative_to(stage).as_posix():digest_file(p) for p in [stage/'addoninfo.txt',*[stage/n for n in mission_files]]}
        (stage/'offline-dlc-manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        check();published=output/'Addons';published.mkdir()
        if crew_stage:os.replace(crew_stage,published/CREW)
        os.replace(stage,published/NAME)
        (output/'INSTALL.txt').write_text('Copy every folder from Addons into left4dead2/addons in your Leave 2 Loader game.\nRestart the game. The normal campaign dropdown routes supplied campaigns to their native offline definitions.\nDisable matching PC campaign ports, PC Campaign Menu and PC Campaign Runtime for this test.\nLoad Offline Xbox DLC first, required L4D1 Survivor Support second, then custom replacements.\n'+(NOTE+'\n' if crew_required else '')+'Original DLC asset archives, BSP files and NAVs are preserved byte for byte. No PC assets, SDK conversion, profile/license edits, or additional executable patches are used.\nThis is an experimental build and still requires console validation.\n',encoding='utf-8')
        with (output/'INSTALL.txt').open('a',encoding='utf-8') as instructions:
            if report.get('pc_chapter_previews'):
                instructions.write('Exception to the native-only asset statement above: missing chapter thumbnails were recovered from your PC installation. Only these UI images were converted; their native 256x128 DXT1 profile and top mip were preserved.\n')
            instructions.write('Use Install Prepared DLC to also install Startup-Audio/startup-audio.360.zip in the next free consecutive root archive slot. Copying only Addons omits required dialogue registration.\nApply the current Loader Patch for music loading and correct L4D1 falling voices. Audio compatibility was confirmed in Xenia; hardware validation remains pending.\n')
        progress('Offline DLC prepared: '+', '.join(CAMPAIGNS[i] for i in ready))
        return report
    except Exception as e:
        report['status']='cancelled' if isinstance(e,InterruptedError) else 'failed';report['error']=str(e)
        raise
    finally:(output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')

def install_prepared_dlc(game,output,progress=lambda _:None):
    from .loader_patcher import safe,emulator_running
    from .registration import merge_registered_addons,order_addon_baselines
    from .keyvalues import parse,decode_text,Token
    import uuid
    if emulator_running():raise ValueError('Close Xenia normally before installing offline DLC')
    game=Path(game).resolve();output=Path(output).resolve();source=output/'Addons'/NAME
    if not has_loader(game):raise ValueError('Apply Leave 2 Loader first')
    report=json.loads((output/'report.json').read_text(encoding='utf-8'))
    if report.get('status')!='built-awaiting-console-test':raise ValueError('Select a completed offline DLC build')
    expected={r['file']:r['sha256'] for r in report['archives']}
    expected.update({r['path']:r['sha256'] for r in report['maps']});expected.update(report['generated_files'])
    expected[report['menu_mission_archive']['file']]=report['menu_mission_archive']['sha256']
    actual=set()
    for p in source.rglob('*'):
        if p.is_symlink():raise ValueError('Linked offline DLC files are unsupported')
        if p.is_file():actual.add(p.relative_to(source).as_posix())
    if actual!=set(expected)|{'offline-dlc-manifest.json'}:raise ValueError('Offline DLC build contains missing or unexpected files')
    for name,digest in expected.items():
        if digest_file(safe(source,name))!=digest:raise ValueError('Offline DLC build changed: '+name)
    crew_spec=report.get('required_survivor_support')
    crew_needed=bool(crew_spec) or any(str(n) in report['campaigns'] for n in range(7,13))
    crew_target=safe(game,'left4dead2/addons/'+CREW);crew_source=output/'Addons'/CREW
    crew_copy=False
    def validate_crew(folder,expected_files=None):
        receipt_path=safe(folder,'leave2-survivors.json')
        if not receipt_path.is_file():raise ValueError('L4D1 crew patch required. Build/install it through Offline DLC first.')
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        if receipt.get('kind')!='native-l4d1-survivors' or receipt.get('revision',1)<2:
            raise ValueError('Update the L4D1 crew patch to the version with working materials and arm mappings')
        for name,digest in (expected_files or receipt['files']).items():
            if digest_file(safe(folder,name))!=digest:raise ValueError('L4D1 crew patch file changed: '+name)
    if crew_needed:
        if crew_spec:validate_crew(crew_source,crew_spec['files'])
        if crew_target.exists():validate_crew(crew_target)
        elif crew_spec:crew_copy=True
        else:raise ValueError('L4D1 crew patch required. Install survivor support first, or rebuild offline DLC to include its companion.')
    state=safe(game,'left4dead2/addonlist.txt');before=state.read_bytes() if state.exists() else b''
    conflicts={'pc campaign runtime','pc campaign menu'}|{(r['title']+' (PC Port)').casefold() for r in report['campaigns'].values()}
    if before:
        enabled=[e.key.value for e in parse(decode_text(before))[0].value if isinstance(e.value,Token) and e.value.value=='1' and e.key.value.casefold() in conflicts]
        if enabled:raise ValueError('Disable these conflicting PC addons before installing native offline DLC: '+', '.join(enabled))
    after,_=merge_registered_addons(before,[NAME,*([CREW] if crew_needed else [])])
    if crew_needed:after=require_crew_enabled(after)
    after=order_addon_baselines(after,[NAME,CREW])
    target=safe(game,'left4dead2/addons/'+NAME)
    if target.exists():raise ValueError('Offline Xbox DLC already exists; preserve or remove it before rebuilding')
    startup=None
    if report.get('startup_audio'):
        from .startup_audio import plan_startup_audio
        spec=report['startup_audio']
        startup=plan_startup_audio(game,safe(output,spec['file']),spec)
    target.parent.mkdir(parents=True,exist_ok=True)
    staging=safe(game,'.leave2-loader/staging/offline-'+uuid.uuid4().hex);staging.mkdir(parents=True)
    pending=staging/NAME
    progress('Copying prepared native DLC into the game…');shutil.copytree(source,pending)
    for name,digest in expected.items():
        if digest_file(safe(pending,name))!=digest:raise ValueError('Installed DLC copy verification failed: '+name)
    if crew_copy:
        shutil.copytree(crew_source,staging/CREW);validate_crew(staging/CREW,crew_spec['files'])
    if emulator_running():raise ValueError('Close Xenia normally before completing installation')
    if (state.read_bytes() if state.exists() else b'')!=before:raise ValueError('Addon states changed; installation stopped before publication')
    backup=state.with_name('addonlist.txt.before-offline-'+uuid.uuid4().hex)
    if before:backup.write_bytes(before)
    published=[]
    try:
        if crew_copy:os.replace(staging/CREW,crew_target);published.append(crew_target)
        os.replace(pending,target);published.append(target)
        if startup:
            # Exclusive creation must never replace an unrelated user's archive.
            with startup['target'].open('xb') as f:
                published.append(startup['target']);f.write(startup['payload'])
            if digest_file(startup['target'])!=report['startup_audio']['sha256']:raise ValueError('Installed startup audio readback mismatch')
            startup['receipt'].parent.mkdir(parents=True,exist_ok=True)
            with startup['receipt'].open('xb') as f:
                published.append(startup['receipt']);f.write(startup['record'])
        temp=state.with_name('addonlist.txt.offline-'+uuid.uuid4().hex);temp.write_bytes(after);os.replace(temp,state)
    except Exception:
        # Only the previously absent target, resolved and checked under this game.
        for path in reversed(published):
            if path.is_dir():shutil.rmtree(path)
            else:path.unlink()
        raise
    return {'status':'installed','folder':str(target),'campaigns':report['campaigns'],'backup':str(backup) if before else None,
        'required_survivor_support_enabled':crew_needed,'survivor_support_installed':crew_copy,
        'startup_audio_installed':bool(startup),'startup_audio_archive':str(startup['target']) if startup else None}
