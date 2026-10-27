"""Explicit destructive mod cleanup plus verified, complete patch-backup rollback."""
from pathlib import Path
import os,re,shutil,uuid,stat
from .loader_patcher import STATE,MAX_FILE,safe,load,digest,write_json,emulator_running

def _plain_tree(root,path):
    """Refuse links/junctions before moving or recursively deleting anything."""
    if not path.resolve().is_relative_to(root.resolve()):raise ValueError('Cleanup path leaves selected game')
    nodes=[path]
    while nodes:
        p=nodes.pop();info=p.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
            raise ValueError('Linked cleanup paths are unsupported: '+str(p))
        if p.is_dir():nodes.extend(p.iterdir())

def restore_clean(patcher,game,progress=lambda _:None,*,acknowledge_mod_deletion=False):
    if not acknowledge_mod_deletion:raise ValueError('Acknowledge permanent deletion of installed converted mods before clean restore')
    if emulator_running():raise ValueError('Close Xenia normally before restoring game files')
    root=patcher.root(game);state=safe(root,STATE);active=safe(root,STATE+'/active.json')
    if not active.is_file():raise ValueError('No active patcher backup was found for this game')
    if (state/'operation.lock').exists():raise ValueError('An active or unfinished patch operation exists')
    if (state/'clean-restore-recovery.json').exists():raise ValueError('An earlier clean restore needs recovery; preserve its remaining mod data')
    active_bytes=active.read_bytes();record=load(active);seen=set();chain=[];current={};desired={}
    while record:
        run=record['backup']
        if not re.fullmatch('[0-9a-f]{32}',run) or run in seen or len(seen)>=64:raise ValueError('Invalid or cyclic backup chain')
        seen.add(run);backup=safe(root,STATE+'/backups/'+run);journal_path=backup/'manifest.json';journal=load(journal_path)
        if journal['status']!='installed' or journal['game']!=str(root):raise ValueError('Backup does not match this installation')
        chain.append((journal_path,journal,journal_path.read_bytes()))
        paths=set()
        for item in journal['files']:
            name=item['path']
            if name.casefold() not in patcher.allowed or name.casefold() in paths:raise ValueError('Unknown or duplicate restore path')
            paths.add(name.casefold());path=safe(root,name)
            if name not in current:
                if not path.is_file() or path.stat().st_size>MAX_FILE:raise ValueError('Missing or oversized patched file: '+name)
                current[name]=path.read_bytes();desired[name]=current[name]
            value=desired[name]
            if (digest(value) if value is not None else None)!=item['after_sha256']:raise ValueError('File changed since patching; restore stopped: '+name)
            old=None
            if item['before_sha256'] is not None:
                saved=safe(backup,'files/'+name)
                if saved.stat().st_size>MAX_FILE:raise ValueError('Oversized backup')
                old=saved.read_bytes()
                if digest(old)!=item['before_sha256']:raise ValueError('Backup integrity failure')
            desired[name]=old
        record=journal.get('previous_active')
    # Only explicitly scoped addon state and extra numbered game archives.
    # Never remove stock zip0/zip1 or an archive present in the earliest backup.
    names=['left4dead2/addons','left4dead2/addonlist.txt','left4dead2/addons.txt',
           'left4dead2/console.log',STATE+'/startup-audio.json',STATE+'/staging']
    game_dir=safe(root,'left4dead2')
    if game_dir.is_dir():
        for p in game_dir.iterdir():
            match=re.fullmatch(r'zip([0-9]+)(?:\.360)?\.zip',p.name,re.I)
            if match and int(match[1])>=2:
                name=p.relative_to(root).as_posix()
                # An official title update already baked in before Loader was
                # installed belongs to that original game, rather than to mods.
                if name=='left4dead2/zip2.360.zip' and name not in desired:
                    official=next((f for f in patcher.manifest['files'] if f['path']==name),None)
                    if official and p.is_file() and p.stat().st_size<=MAX_FILE and digest(p.read_bytes())==official['target_sha256']:continue
                if name not in desired:names.append(name)
    targets=[]
    for name in names:
        path=safe(root,name)
        if path.exists():_plain_tree(root,path);targets.append((name,path))
    lock=state/'operation.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    trash=safe(root,STATE+'/clean-restore-trash/'+uuid.uuid4().hex);moved=[];committed=[]
    try:
        if active.read_bytes()!=active_bytes:raise ValueError('Active backup changed')
        for name,data in current.items():
            if safe(root,name).read_bytes()!=data:raise ValueError('Game changed during restore: '+name)
        trash.mkdir(parents=True)
        for index,(name,path) in enumerate(targets):
            _plain_tree(root,path);destination=trash/str(index)
            os.replace(path,destination);moved.append((name,destination))
        for name,data in desired.items():
            progress('Restoring original '+name)
            if data is None:safe(root,name).unlink()
            else:patcher._replace(root,name,data)
            committed.append(name);path=safe(root,name)
            if (path.read_bytes() if path.exists() else None)!=data:raise OSError('Restored file verification failed: '+name)
        for path,journal,_ in chain:
            journal['status']='restored-clean';write_json(path,journal)
        active.unlink()
    except Exception as error:
        try:
            for name in reversed(committed):patcher._replace(root,name,current[name])
            for name,path in reversed(moved):os.replace(path,safe(root,name))
            for path,_,data in chain:path.write_bytes(data)
            active.write_bytes(active_bytes)
        except Exception as recovery:
            write_json(state/'clean-restore-recovery.json',{'status':'recovery-required','trash':str(trash),
                'moved':[(name,str(path)) for name,path in moved],'error':str(error),'recovery_error':str(recovery)})
            raise RuntimeError('Clean restore needs recovery; preserved all remaining mod data at '+str(trash)) from recovery
        if trash.exists():trash.rmdir()
        raise
    finally:
        lock.unlink(missing_ok=True)
    # Destructive disposal is last: original files have all been verified.
    progress('Permanently deleting installed addons and extra archives…')
    try:
        _plain_tree(root,trash);shutil.rmtree(trash)
    except (OSError,ValueError) as error:
        return {'status':'restored-clean-cleanup-required','game':str(root),'backup':str(chain[-1][0].parent),
                'cleanup_pending':str(trash),'error':str(error),'removed_paths':[n for n,_ in targets]}
    return {'status':'restored-clean','game':str(root),'backup':str(chain[-1][0].parent),
            'removed_paths':[n for n,_ in targets],'restored_backup_layers':len(chain)}
