"""Register managed addon folders while preserving existing checkbox choices."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib
from .keyvalues import parse,decode_text,Token,tokens


def merge_registered_addons(data,names):
    text=decode_text(data) if data else '"AddonList"\n{\n}\n'
    roots=parse(text)
    if len(roots)!=1 or roots[0].key.value.lower()!='addonlist' or not isinstance(roots[0].value,list):raise ValueError('Expected one AddonList block')
    fields=roots[0].value;existing=set()
    for entry in fields:
        if not isinstance(entry.value,Token):raise ValueError('Addon state must be a scalar')
        key=entry.key.value.casefold()
        if key in existing:raise ValueError('Duplicate addon state: '+entry.key.value)
        existing.add(key)
    added=[]
    for name in names:
        if not name or any(c in name for c in '\\/:"\r\n\0'):raise ValueError('Unsafe addon folder name')
        if name.casefold() not in existing:added.append(name);existing.add(name.casefold())
    if not added:return data or text.encode('utf-8'),[]
    closing=[t for t in tokens(text) if t.kind=='brace' and t.value=='}'][-1]
    insertion=''.join('  "'+name+'" "1"\n' for name in added)
    text=text[:closing.start]+insertion+text[closing.start:];parse(text)
    return text.encode('utf-8'),added



def order_addon_baselines(data,names):
    """Mount declared baseline packages first; preserve every checkbox and other order.

    The verified Loader adds successive paths at the search-path head, so later
    replacement addons override the earlier baseline assets.
    """
    text=decode_text(data);roots=parse(text)
    if len(roots)!=1 or roots[0].key.value.lower()!='addonlist' or not isinstance(roots[0].value,list):raise ValueError('Expected AddonList')
    entries=roots[0].value;rank={name.casefold():i for i,name in enumerate(names)}
    if any(not isinstance(e.value,Token) for e in entries):raise ValueError('Addon state must be scalar')
    if len({e.key.value.casefold() for e in entries})!=len(entries):raise ValueError('Duplicate addon state')
    ordered=sorted(entries,key=lambda e:rank.get(e.key.value.casefold(),len(rank)))
    if ordered==entries:return data
    return ('"AddonList"\n{\n'+''.join('  '+text[e.key.start:e.value.end]+'\n' for e in ordered)+'}\n').encode('utf-8')


def register_installed_addons(game):
    root=Path(game).resolve()
    if (root/'left4dead2').is_dir():root=root/'left4dead2'
    addons=root/'addons'
    if not addons.is_dir():raise ValueError('Choose a game directory containing left4dead2/addons, or left4dead2 itself')
    names=[];baseline_roles=[]
    for folder in sorted(addons.iterdir()):
        if not folder.is_dir() or folder.is_symlink():continue
        info=folder/'addoninfo.txt'
        if not info.is_file():continue
        entries=parse(decode_text(info.read_bytes()))
        if len(entries)!=1 or not isinstance(entries[0].value,list):continue
        fields={e.key.value.casefold():e.value.value for e in entries[0].value if isinstance(e.value,Token)}
        if fields.get('leave2_managed')=='1':
            names.append(folder.name)
            role=fields.get('leave2_role')
            if role in ('base_resources','campaign_base'):baseline_roles.append((1 if role=='base_resources' else 0,folder.name))
    state=root/'addonlist.txt';before=state.read_bytes() if state.exists() else b''
    after,added=merge_registered_addons(before,names)
    after=order_addon_baselines(after,[name for _,name in sorted(baseline_roles)])
    backup=None
    if after!=before:
        if state.exists():
            stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup=root/('addonlist.txt.before-registration-'+stamp);backup.write_bytes(before)
        # Do not overwrite a state changed by the game since we read it.
        if state.exists() and state.read_bytes()!=before:raise ValueError('Addon states changed during registration; close the game and retry')
        state.write_bytes(after)
    return {'game':str(root),'added':added,'managed_folders':names,'backup':str(backup) if backup else None,
        'before_sha256':hashlib.sha256(before).hexdigest(),'after_sha256':hashlib.sha256(after).hexdigest()}
