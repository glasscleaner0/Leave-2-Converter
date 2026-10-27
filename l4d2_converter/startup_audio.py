"""Verified startup registration archive for native offline DLC dialogue."""
from pathlib import Path
import hashlib,json,re
from .archive import aligned_zip, XboxZip
from .loader_patcher import safe
from .native_dialogue import startup_dialogue

RECEIPT='.leave2-loader/startup-audio.json'
sha=lambda data:hashlib.sha256(data).hexdigest()


def export_startup_audio(game,donors,output,*,stock_archives=None,startup_members=None):
    game=Path(game);output=Path(output)
    stock=list(stock_archives) if stock_archives is not None else sorted((game/'left4dead2').glob('zip*.zip'),key=lambda p:int(re.search(r'zip(\d+)',p.name)[1]))
    try:members,report=startup_dialogue([*stock,*donors])
    except ValueError as error:
        if str(error).startswith('Missing response-rule include'):
            raise ValueError('Native dialogue needs shared files from the other Xbox DLC packages. Add The Passing and The Sacrifice sources, plus Cold Stream when importing it. '+str(error)) from error
        raise
    report['kind']='native-dialogue-startup-registration'
    report['method_validation']='Normal dialogue confirmed by user in Xenia; each new build still needs runtime validation.'
    for name,data in (startup_members or {}).items():
        if name in members and members[name]!=data:raise ValueError('Conflicting startup support file: '+name)
        members[name]=data
    output.mkdir(parents=True,exist_ok=True)
    target=output/'startup-audio.360.zip';target.write_bytes(aligned_zip(members))
    check=XboxZip(target)
    if any(check.read(n)!=data for n,data in members.items()):raise ValueError('Startup audio readback mismatch')
    return {'revision':1,'file':'Startup-Audio/'+target.name,'sha256':sha(target.read_bytes()),
            'bytes':target.stat().st_size,'registration':report,
            'requires_native_dlc_addon_enabled':True,'startup_archive_required':True,
            'startup_visual_files':sorted(startup_members or {})}


def plan_startup_audio(game,source,spec):
    """Read-only plan. Caller publishes this together with its addon transaction."""
    game=Path(game);source=Path(source)
    payload=source.read_bytes()
    if sha(payload)!=spec['sha256']:raise ValueError('Startup audio build changed')
    z=XboxZip(payload)
    for name in z.entries:z.read(name)
    receipt=safe(game,RECEIPT)
    if receipt.exists():
        prior=json.loads(receipt.read_text(encoding='utf-8'));target=safe(game,prior['archive'])
        if not target.is_file() or sha(target.read_bytes())!=prior['sha256']:
            raise ValueError('Installed startup audio changed; preserve it before rebuilding')
        if prior['sha256']!=spec['sha256']:
            raise ValueError('Different startup audio already installed; preserve it before rebuilding')
        return None
    slots=[]
    for path in (game/'left4dead2').glob('zip*.zip'):
        match=re.fullmatch(r'zip(\d+)\.360\.zip',path.name,re.I)
        if not match:raise ValueError('Startup audio requires the supported .360.zip layout')
        slots.append(int(match[1]))
    if not slots or sorted(slots)!=list(range(max(slots)+1)):
        raise ValueError('Startup archive numbering has gaps; preserve and correct the layout first')
    slot=max(slots)+1
    if slot>999:raise ValueError('Too many startup archives')
    name=f'left4dead2/zip{slot}.360.zip';target=safe(game,name)
    if target.exists():raise ValueError('Startup archive slot already exists')
    record={'schema':1,'revision':1,'archive':name,'sha256':spec['sha256'],
            'requires_native_dlc_addon_enabled':True}
    return {'target':target,'payload':payload,'receipt':receipt,
            'record':json.dumps(record,indent=2).encode('utf-8')}
