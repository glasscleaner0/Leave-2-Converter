"""User-approved removal of a known incompatible console Director setting."""
import hashlib,re
from .scripts import decode_script,transform

_ignored=re.compile(rb'//[^\r\n]*|/\*.*?\*/|@"(?:""|[^"])*"|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',re.S)
_rule=re.compile(rb'^[ \t]*SpawnSetRule[ \t]*=[ \t]*SPAWN_FINALE[ \t]*[,;]?[ \t]*(?=\r?$)',re.M)

def finale_rule_lines(data):
    masked=_ignored.sub(lambda m:re.sub(rb'[^\r\n]',b' ',m.group()),data)
    rows=[]
    for m in _rule.finditer(masked):
        start=data.rfind(b'\n',0,m.start())+1
        end=data.find(b'\n',m.end())
        if end<0:end=len(data)
        if end>start and data[end-1:end]==b'\r':end-=1
        rows.append({'line':data.count(b'\n',0,start)+1,'start':start,'end':end})
    return rows

def repair_finale_rules(game,prompt=None,cancelled=lambda:False):
    candidates=[]
    for p in sorted((game/'scripts/vscripts').rglob('*')):
        if not p.is_file() or p.suffix.lower() not in ('.nut','.nuc'):continue
        original=p.read_bytes()
        try:plain=decode_script(original) if p.suffix.lower()=='.nuc' else original
        except (ValueError,UnicodeError):continue # Existing conversion validation reports this.
        matches=finale_rule_lines(plain)
        if matches:candidates.append((p,original,plain,matches))
    if not candidates:return []
    summary=[{'path':p.relative_to(game).as_posix(),'lines':[m['line'] for m in matches]} for p,_,_,matches in candidates]
    accepted=bool(prompt(summary)) if prompt else False
    if cancelled():raise InterruptedError('Cancelled before script compatibility changes')
    records=[]
    for (p,original,plain,matches),row in zip(candidates,summary):
        after=plain
        if accepted:
            for m in reversed(matches):after=after[:m['start']]+after[m['end']:]
            result=transform(after,decrypt=False) if p.suffix.lower()=='.nuc' else after
            if p.suffix.lower()=='.nuc' and decode_script(result)!=after:raise ValueError('Script compatibility encryption check failed')
            p.write_bytes(result)
        else:result=original
        records.append({**row,'setting':'SpawnSetRule = SPAWN_FINALE','action':'removed' if accepted else 'kept',
            'reason':'Known Xbox compatibility issue: SPAWN_FINALE can be undefined and abort Director script initialization. Removing the setting can change spawning behavior.',
            'before_sha256':hashlib.sha256(original).hexdigest(),'after_sha256':hashlib.sha256(result).hexdigest()})
    return records
