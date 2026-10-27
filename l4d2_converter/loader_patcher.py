"""Hash-locked extracted-game patching with transactional backups and restore."""
from pathlib import Path,PurePosixPath
import hashlib,json,os,shutil,struct,subprocess,uuid,zlib

STATE='.leave2-loader'
MAX_FILE=64*1024**2
digest=lambda b:hashlib.sha256(b).hexdigest()
def relative(name):
    p=PurePosixPath(name)
    if not name or p.is_absolute() or any(x in ('','.','..') for x in name.split('/')) or any(c in name for c in ':\\\0'):
        raise ValueError('Unsafe patch path')
    return p
def safe(root,name):
    p=root.joinpath(*relative(name).parts)
    if not p.resolve().is_relative_to(root.resolve()):raise ValueError('Patch path leaves the selected folder')
    for parent in [p,*p.parents]:
        if parent==root:break
        if parent.is_symlink():raise ValueError('Linked patch paths are unsupported')
    return p
def load(path):return json.loads(path.read_text(encoding='utf-8'))
def has_loader(game):
    root=Path(game)
    if safe(root,'left4dead2/bin/Leave2loader_version.txt').is_file():return True
    # Older development installs predate the version marker. Accept only the
    # exact current, verified Loader UI, not an arbitrary modified executable.
    try:
        from .app_paths import application_home
        manifest=load(application_home()/'tools/loader-patch/manifest.json')
        entry=next(f for f in manifest['files'] if f['path']=='bin/GameUI_360.dll')
        path=safe(root,entry['path'])
        return path.is_file() and digest(path.read_bytes())==entry['target_sha256']
    except (OSError,ValueError,KeyError,StopIteration):return False
def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(value,indent=2),encoding='utf-8');os.replace(temp,path)
def emulator_running():
    if os.name!='nt':return False
    p=subprocess.run(['tasklist','/FO','CSV','/NH','/FI','IMAGENAME eq xenia*'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=15)
    if p.returncode:raise ValueError('Could not check for a running emulator; close it before patching')
    return any(line.lower().startswith(b'"xenia') for line in p.stdout.splitlines())
def bounded_inflate(data,size):
    if not 0<=size<=MAX_FILE:raise ValueError('Patch output exceeds size limit')
    d=zlib.decompressobj();out=d.decompress(data,size+1)
    if len(out)!=size or not d.eof or d.unused_data or d.unconsumed_tail:raise ValueError('Invalid patch payload size or trailing data')
    return out

class LoaderPatcher:
    def __init__(self,bundle):
        self.bundle=Path(bundle).resolve();self.manifest=load(self.bundle/'manifest.json')
        if self.manifest.get('schema')!=1:raise ValueError('Unsupported patch manifest')
        names=[f['path'].casefold() for f in self.manifest['files']]
        if len(names)!=len(set(names)) or not 1<=len(names)<=64:raise ValueError('Invalid or duplicate patch entries')
        for f in self.manifest['files']:relative(f['path'])
        self.allowed=set(names)
    def root(self,game):
        root=Path(game).resolve()
        if not root.is_dir() or not (root/'default.xex').is_file():raise ValueError('Choose the extracted game folder containing default.xex')
        return root
    def prepare(self,game):
        root=self.root(game)
        addons=safe(root,'left4dead2/addons')
        if addons.exists() and not addons.is_dir():raise ValueError('Expected an addons folder: left4dead2/addons')
        if safe(root,STATE+'/operation.lock').exists():raise ValueError('An unfinished or active patch operation exists; preserve its backups before recovery')
        if safe(root,STATE+'/clean-restore-recovery.json').exists():raise ValueError('A clean restore needs recovery; preserve its backups and remaining mod data')
        operations=[]
        files=self.manifest['files']
        if self.manifest.get('profile_support'):
            default=next(f for f in files if f['path']=='default.xex');value=digest((root/'default.xex').read_bytes())
            known_original=any(v['source_sha256']==value for v in default['variants'])
            updated=value==default['target_sha256']
            if not updated and not known_original:
                for f in files:
                    if not f.get('loader_module'):continue
                    p=safe(root,f['path'])
                    if p.is_file() and p.stat().st_size<=MAX_FILE and digest(p.read_bytes()) in (f['target_sha256'],f.get('official_sha256')):updated=True
            if updated:files=[f for f in files if f.get('loader_module') or f.get('loader_marker') or f['path'].startswith('left4dead2/zip')]
        for f in files:
            path=safe(root,f['path'])
            if path.exists() and not path.is_file():raise ValueError('Expected a file: '+f['path'])
            if path.exists() and path.stat().st_size>MAX_FILE:raise ValueError('Unexpected oversized patch target: '+f['path'])
            old=path.read_bytes() if path.exists() else None;before=digest(old) if old is not None else None
            if before==f['target_sha256']:continue
            variant=next((v for v in f['variants'] if v['source_sha256']==before),None)
            if variant:
                packed=safe(self.bundle,variant['payload']).read_bytes()
                if digest(packed)!=variant['payload_sha256'] or packed[:7]!=b'L2XOR1\0' or len(old)!=variant['source_bytes']:raise ValueError('Invalid binary patch: '+f['path'])
                size=struct.unpack_from('<Q',packed,7)[0]
                if size!=f['target_bytes']:raise ValueError('Invalid binary patch target size')
                xor=bounded_inflate(packed[15:],size);source=old[:size]+bytes(max(0,size-len(old)))
                new=bytes(a^b for a,b in zip(xor,source))
            elif old is None and f.get('allow_absent') and f.get('new_payload'):
                new=bounded_inflate(safe(self.bundle,f['new_payload']).read_bytes(),f['target_bytes'])
            else:raise ValueError('Unknown or modified file / archive conflict: '+f['path']+'. Use a supported clean copy; no files changed.')
            if digest(new)!=f['target_sha256']:raise ValueError('Reconstructed patch hash mismatch: '+f['path'])
            operations.append({'path':f['path'],'before_sha256':before,'after_sha256':f['target_sha256'],'old':old,'new':new})
        return root,operations
    def inspect(self,game):
        root,ops=self.prepare(game)
        return {'status':'ready' if ops else 'already-installed','game':str(root),'changed_files':[o['path'] for o in ops],'backup_bytes':sum(len(o['old'] or b'') for o in ops),'patch_id':self.manifest['patch_id']}
    def _replace(self,root,name,data):
        path=safe(root,name);path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_name(path.name+'.l2-'+uuid.uuid4().hex+'.tmp')
        try:
            temp.write_bytes(data)
            if digest(temp.read_bytes())!=digest(data):raise OSError('Staged file verification failed')
            os.replace(temp,path)
        finally:temp.unlink(missing_ok=True)
    def apply(self,game,progress=lambda _:None):
        if emulator_running():raise ValueError('Close Xenia normally before patching the game')
        root,ops=self.prepare(game)
        addons=safe(root,'left4dead2/addons')
        if not ops:
            addons.mkdir(parents=True,exist_ok=True)
            return self.inspect(game)
        required=sum(len(o['old'] or b'')+len(o['new']) for o in ops)+32*1024**2
        if shutil.disk_usage(root).free<required:raise ValueError('Not enough free space for verified backups and patch staging')
        state=safe(root,STATE);state.mkdir(exist_ok=True);lock=state/'operation.lock'
        fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
        run=uuid.uuid4().hex;backup=safe(root,STATE+'/backups/'+run);backup.mkdir(parents=True)
        journal={'schema':1,'game':str(root),'patch_id':self.manifest['patch_id'],'status':'preparing','files':[{k:v for k,v in o.items() if k not in ('old','new')} for o in ops]}
        active=state/'active.json'
        if active.is_file():journal['previous_active']=load(active)
        committed=[];created_addons=False
        try:
            for o in ops:
                if o['old'] is not None:
                    path=safe(backup,'files/'+o['path']);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(o['old'])
                    if digest(path.read_bytes())!=o['before_sha256']:raise OSError('Backup verification failed')
            journal['status']='installing';write_json(backup/'manifest.json',journal)
            for o in ops:
                path=safe(root,o['path']);current=digest(path.read_bytes()) if path.exists() else None
                if current!=o['before_sha256']:raise ValueError('Game changed since compatibility check: '+o['path'])
                progress('Patching '+o['path']);self._replace(root,o['path'],o['new']);committed.append(o)
                if digest(path.read_bytes())!=o['after_sha256']:raise OSError('Installed file hash mismatch')
            if not addons.exists():
                addons.mkdir(parents=True);created_addons=True
            journal['status']='installed';write_json(backup/'manifest.json',journal)
            write_json(state/'active.json',{'backup':run,'patch_id':self.manifest['patch_id']})
            progress('Loader installed. The official update is integrated; disable the separate Aurora L4D2 title update for this copy.')
            return {'status':'installed','changed_files':[o['path'] for o in ops],'backup':str(backup),'game':str(root)}
        except Exception:
            try:
                if created_addons and addons.is_dir() and not any(addons.iterdir()):addons.rmdir()
                for o in reversed(committed):
                    path=safe(root,o['path'])
                    if digest(path.read_bytes())!=o['after_sha256']:raise ValueError('Rollback conflict; preserve '+str(backup))
                    if o['old'] is None:path.unlink()
                    else:self._replace(root,o['path'],o['old'])
                journal['status']='failed-rolled-back';write_json(backup/'manifest.json',journal)
            except Exception as rollback:
                journal['status']='recovery-required';journal['recovery_error']=str(rollback);write_json(backup/'manifest.json',journal)
                raise RuntimeError('Patch failed and needs recovery from '+str(backup)) from rollback
            raise
        finally:lock.unlink(missing_ok=True)
    def restore(self,game,progress=lambda _:None):
        if emulator_running():raise ValueError('Close Xenia normally before restoring game files')
        root=self.root(game);state=safe(root,STATE);active=state/'active.json'
        if not active.is_file():raise ValueError('No active patcher backup was found for this game')
        run=load(active)['backup']
        if len(run)!=32 or any(c not in '0123456789abcdef' for c in run):raise ValueError('Invalid backup ID')
        backup=safe(root,STATE+'/backups/'+run);journal=load(backup/'manifest.json')
        if journal['status']!='installed' or journal['game']!=str(root):raise ValueError('Backup does not match this installation')
        original={}
        for o in journal['files']:
            if o['path'].casefold() not in self.allowed:raise ValueError('Unknown restore path')
            path=safe(root,o['path'])
            if not path.is_file() or digest(path.read_bytes())!=o['after_sha256']:raise ValueError('File changed since patching; restore stopped: '+o['path'])
            data=safe(backup,'files/'+o['path']).read_bytes() if o['before_sha256'] is not None else None
            if data is not None and digest(data)!=o['before_sha256']:raise ValueError('Backup integrity failure')
            original[o['path']]=data
        lock=state/'operation.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
        committed=[];current={o['path']:safe(root,o['path']).read_bytes() for o in journal['files']}
        try:
            for o in reversed(journal['files']):
                if digest(safe(root,o['path']).read_bytes())!=o['after_sha256']:raise ValueError('Game changed during restore: '+o['path'])
                progress('Restoring '+o['path']);data=original[o['path']]
                if data is None:safe(root,o['path']).unlink()
                else:self._replace(root,o['path'],data)
                committed.append(o['path'])
                path=safe(root,o['path'])
                if (digest(path.read_bytes()) if path.exists() else None)!=o['before_sha256']:raise OSError('Restored file hash mismatch')
            journal['status']='restored';write_json(backup/'manifest.json',journal)
            if journal.get('previous_active'):write_json(active,journal['previous_active'])
            else:active.unlink()
            return {'status':'restored','backup':str(backup),'game':str(root)}
        except Exception:
            for name in reversed(committed):self._replace(root,name,current[name])
            raise
        finally:lock.unlink(missing_ok=True)

    def restore_clean(self,game,progress=lambda _:None,*,acknowledge_mod_deletion=False):
        from .clean_restore import restore_clean
        return restore_clean(self,game,progress,acknowledge_mod_deletion=acknowledge_mod_deletion)
