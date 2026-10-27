"""Read-only index of installed console resources, without staging native assets."""
from pathlib import Path
from .archive import XboxZip, safe_name
from .keyvalues import parse, decode_text, Token

class LooseFile:
    def __init__(self, path): self.path = path
    def read(self, name): return self.path.read_bytes()

def overlay_install(index, requested):
    root = Path(requested).expanduser().resolve()
    if (root/'left4dead2').is_dir(): root = root/'left4dead2'
    if not root.is_dir() or not any((root/name).is_file() for name in ('gameinfo.txt','gameinfo.xtx')):
        raise ValueError('Choose the modded L4D2 install containing left4dead2/gameinfo.xtx (or gameinfo.txt), or left4dead2 itself')
    report = {'root':str(root), 'enabled_addons':[], 'archives':[], 'loose_files':0,
              'note':'Read-only dependencies assumed present at runtime; no native resources copied into the addon.'}
    def put(name, reader):
        name = safe_name(name)
        if name == '__preload_section.pre': return
        index[name.replace('.360.', '.')] = (reader, name)
    def mount(folder):
        # Numbered archives then loose files, matching normal override priority.
        archives = sorted(folder.glob('zip*.zip'), key=lambda p:(int(p.name[3:].split('.')[0]) if p.name[3:].split('.')[0].isdigit() else -1,p.name))
        for p in archives:
            if p.is_symlink(): raise ValueError('Symlink in modded console reference')
            try: z = XboxZip(p)
            except (ValueError,OSError) as error:
                raise ValueError(f'Cannot index console archive {p}: {error}') from error
            for name in z.entries: put(name,z)
            report['archives'].append(str(p))
        for prefix in ('maps','missions','scripts','materials','models','sound','scenes','particles','resource','reslists_xbox'):
            directory = folder/prefix
            if directory.is_symlink(): raise ValueError('Symlink in modded console reference')
            if not directory.is_dir(): continue
            # No recursive traversal through junctions/symlinks.
            import os, stat
            for current,dirs,files in os.walk(directory,followlinks=False):
                for name in dirs+files:
                    p=Path(current)/name;st=p.lstat()
                    if p.is_symlink() or getattr(st,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400):
                        raise ValueError('Symlink/junction in modded console reference')
                for name in sorted(files):
                    p=Path(current)/name;put(p.relative_to(folder).as_posix(),LooseFile(p));report['loose_files']+=1
    mount(root)
    state=root/'addonlist.txt'
    if state.is_file():
        blocks=parse(decode_text(state.read_bytes()))
        if len(blocks)!=1 or blocks[0].key.value.lower()!='addonlist' or not isinstance(blocks[0].value,list):
            raise ValueError('Invalid addonlist.txt in modded console reference')
        seen=set()
        for e in blocks[0].value:
            name=e.key.value
            if not isinstance(e.value,Token) or name.casefold() in seen: raise ValueError('Invalid/duplicate addon state')
            seen.add(name.casefold())
            if e.value.value=='0': continue
            if e.value.value!='1': raise ValueError('Addon state must be 0 or 1')
            if '/' in name or '\\' in name or name in ('.','..'): raise ValueError('Unsafe addon reference')
            folder=root/'addons'/safe_name(name)
            if not folder.is_dir(): continue
            if folder.is_symlink() or not folder.resolve().is_relative_to(root): raise ValueError('Unsafe addon reference')
            mount(folder);report['enabled_addons'].append(name)
    report['indexed_paths']=len(index)
    return report
