"""Bounded, streaming extraction and explicit multipart input merging."""
from pathlib import Path
import hashlib
import stat
from .archive import Vpk, safe_name


def metadata_input(name):
    p=Path(name)
    return (p.name in ('thumbs.db','desktop.ini','.ds_store') or
            name in ('addoninfo.txt','readme.txt') or
            p.parent == Path('.') and p.stem == 'addonimage')


def extract_inputs(paths, target, max_bytes=4 * 1024**3):
    target = Path(target)
    manifest = {}
    total = 0
    seen_sources = set()
    for requested in paths:
        path = Path(requested).resolve()
        if path in seen_sources: raise ValueError('Duplicate input package: ' + str(path))
        seen_sources.add(path)
        if path.is_file():
            archive = Vpk(path)
            entries = ((n, len(e[1])+e[4], lambda n=n:archive.read(n)) for n,e in archive.entries.items())
        elif path.is_dir():
            def folder_entries():
                for item in sorted(path.rglob('*')):
                    metadata = item.lstat()
                    if item.is_symlink() or getattr(metadata,'st_file_attributes',0) & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400):
                        raise ValueError('Symlinks/junctions are not supported in extracted input')
                    if item.is_file():
                        yield safe_name(item.relative_to(path).as_posix()),item.stat().st_size,item.read_bytes
            entries = folder_entries()
        else: raise ValueError('Input VPK/folder does not exist: ' + str(path))
        source_names = set()
        for name, size, read in entries:
            if name in source_names: raise ValueError('Case-insensitive input collision: ' + name)
            source_names.add(name)
            if '.360.' in name or '.ps3.' in name:
                raise ValueError('Input must contain PC assets, not previously converted assets: ' + name)
            if size > 512 * 1024**2: raise ValueError('Input asset exceeds 512 MiB limit: ' + name)
            if name not in manifest and total + size > max_bytes:
                raise ValueError('Extracted input exceeds 4 GiB limit')
            data = read()
            if len(data) != size: raise ValueError('Input file changed size while reading: ' + name)
            digest = hashlib.sha256(data).hexdigest()
            if name in manifest:
                old = manifest[name]
                if old['sha256'] != digest:
                    if not metadata_input(name):
                        raise ValueError('Conflicting multipart input asset: ' + name + ' in ' + str(path))
                    old.setdefault('metadata_variants',[]).append({'source':str(path),'sha256':digest})
                old['sources'].append(str(path))
                continue
            dst = target/name
            dst.parent.mkdir(parents=True,exist_ok=True)
            dst.write_bytes(data)
            total += size
            manifest[name] = {'path':name,'bytes':size,'sha256':digest,'sources':[str(path)]}
    return list(manifest.values())
