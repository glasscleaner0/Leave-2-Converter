"""Read-only, demand-loaded local dependency index; no whole-mod merging."""
from pathlib import Path
import hashlib
import json
import os
import stat
from .archive import Vpk, safe_name

ROOTS={'models','materials','sound','scripts','particles','scenes','resource'}


def dependency_location(input_path, folder='', same=False):
    if same:
        source=Path(input_path)
        return source.parent if source.is_file() else source
    return Path(folder) if folder else None


class DependencyLibrary:
    def __init__(self, root, excluded=(), cancelled=lambda:False):
        self.index={};self.used=[];self.warnings=[];self.cache={}
        self.root=Path(root).resolve()
        if not self.root.is_dir():raise ValueError('Dependency location must be an existing folder')
        excluded=[Path(p).resolve() for p in excluded if p]
        self.packages=0;self.loose_files=0;scanned=0
        def scan_error(error):self.warnings.append({'source':str(error.filename),'reason':str(error)})
        for directory,dirs,files in os.walk(self.root,followlinks=False,onerror=scan_error):
            if cancelled():raise InterruptedError('Dependency scan cancelled')
            base=Path(directory)
            def blocked(path):
                attrs=path.lstat()
                return (path.is_symlink() or getattr(attrs,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400)
                        or any(path.resolve()==p or p in path.resolve().parents for p in excluded))
            dirs[:]=[d for d in sorted(dirs) if d not in ('.git','.work','__pycache__') and not blocked(base/d)]
            report=base/'report.json'
            if report.is_file() and report.stat().st_size<8*1024**2:
                try:
                    r=json.loads(report.read_text(encoding='utf8'))
                    if isinstance(r,dict) and isinstance(r.get('jobs'),list) and r.get('version') and r.get('status'):
                        dirs[:]=[];continue # historical converter output, not source content
                except (ValueError,OSError):pass
            for filename in sorted(files):
                if cancelled():raise InterruptedError('Dependency scan cancelled')
                scanned+=1
                if scanned>200000:raise ValueError('Dependency scan exceeds 200,000 files; choose a narrower folder')
                path=base/filename
                if blocked(path):continue
                if path.suffix.lower()=='.vpk':
                    # Chunk files belong to their directory VPK, not separate packages.
                    if len(path.stem)>4 and path.stem[-4]=='_' and path.stem[-3:].isdigit() and path.with_name(path.stem[:-3]+'dir.vpk').exists():continue
                    try:
                        archive=Vpk(path);self.packages+=1
                        for name in archive.entries:self.add(name,(archive,name,str(path)))
                    except (ValueError,OSError) as e:self.warnings.append({'source':str(path),'reason':str(e)})
                else:
                    parts=path.relative_to(self.root).parts
                    start=next((i for i,p in enumerate(parts) if p.lower() in ROOTS),None)
                    if start is None:continue
                    try:name=safe_name('/'.join(parts[start:]))
                    except ValueError as e:self.warnings.append({'source':str(path),'reason':str(e)});continue
                    if self.add(name,(None,path,str(path))):self.loose_files+=1

    def add(self,name,source):
        if name.split('/')[0] not in ROOTS or '.360.' in name or '.ps3.' in name:return False
        self.index.setdefault(name,[]).append(source)
        return True

    def read(self,name):
        if name in self.cache:return self.cache[name]
        sources=self.index.get(name,[])
        if not sources:return None
        selected=None;digest=None
        for archive,key,origin in sources:
            if archive is None:
                if key.stat().st_size>512*1024**2:raise ValueError('Dependency asset exceeds 512 MiB: '+str(key))
                data=key.read_bytes()
            else:data=archive.read(key)
            current=hashlib.sha256(data).hexdigest()
            if digest is not None and digest!=current:
                raise ValueError('Conflicting dependency candidates for '+name+': '+', '.join(s[2] for s in sources))
            selected=data;digest=current
        self.used.append({'path':name,'sha256':digest,'bytes':len(selected),'sources':[s[2] for s in sources]})
        self.cache[name]=selected
        return selected

    def summary(self):
        return {'root':str(self.root),'vpk_packages':self.packages,'loose_assets':self.loose_files,
                'indexed_paths':len(self.index),'used':self.used,'warnings':self.warnings}
