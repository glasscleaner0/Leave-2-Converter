"""Explicit MP3 path adaptation in a private campaign staging directory."""
import hashlib
import re
from pathlib import Path
from .audio import fallback_xwv
from .formats import bsp_lump
from .compatibility import replace_entity_lump

def replace_literals(data,old,new):
    # Replace complete quoted paths only. Prefix characters used by Source's
    # sound system are retained. No substring or dynamically built path rewrite.
    path=rb'[\\/]{1,2}'.join(re.escape(part.encode()) for part in old.replace('\\','/').split('/'))
    pattern=re.compile(rb'"([*#@><^)}!?]*)(sound[\\/]{1,2})?'+path+rb'"',re.I)
    return pattern.subn(lambda m:b'"'+m.group(1)+(m.group(2) or b'')+new.encode()+b'"',data)

def prepare_mpeg_audio(game,scratch,decoder='',timeout=120):
    game=Path(game);files={p.relative_to(game).as_posix():p for p in game.rglob('*') if p.is_file()}
    records=[];occupied={name.casefold() for name in files}
    for name,p in sorted(files.items()):
        if not name.startswith('sound/') or not name.endswith('.mp3'):continue
        old=name.removeprefix('sound/');new=old[:-4]+'.wav'
        payload=p.read_bytes();digest=hashlib.sha256(payload).hexdigest()
        existing='sound/'+new
        collision=existing.casefold() in occupied or (game/existing).exists()
        if collision:
            stem=old[:-4]+'_l2c_mp3_'+digest[:12];new=stem+'.wav';counter=2
            while ('sound/'+new).casefold() in occupied or (game/('sound/'+new)).exists():
                new=stem+'_'+str(counter)+'.wav';counter+=1
        target=game/('sound/'+new)
        changes=[]
        for owner,q in files.items():
            if owner.endswith('.bsp'):
                before=q.read_bytes();entities=bsp_lump(before,0)
                after,count=replace_literals(entities,old,new)
                if count:changes.append((q,replace_entity_lump(before,after),owner,count))
            elif (owner.startswith('scripts/') and owner.endswith(('.nut','.txt','.cfg')) or
                  owner.startswith('maps/') and owner.endswith('_level_sounds.txt')):
                after,count=replace_literals(q.read_bytes(),old,new)
                if count:changes.append((q,after,owner,count))
        # Keep every audio asset as decoded WAV, even when no direct consumer is
        # visible. Otherwise it reaches the later unsupported-MP3 check. Report
        # unknown/dynamically assembled references rather than dropping content.
        _,info=fallback_xwv(p,scratch,decoder,timeout)
        decoded=Path(scratch)/(digest+'.wav')
        if not decoded.is_file():raise ValueError('MP3 decoder produced no staged WAV')
        target.write_bytes(decoded.read_bytes())
        occupied.add(('sound/'+new).casefold())
        for q,after,owner,count in changes:q.write_bytes(after)
        # Commit this source renaming only in staging after decode validation.
        p.unlink()
        records.append({'source':name,'output_source':'sound/'+new,'source_sha256':digest,
            'references':[{'owner':owner,'count':count} for _,_,owner,count in changes],**info,
            'existing_wav_preserved':existing if collision else None,
            'collision_resolved_with_unique_name':collision,
            'no_direct_references_found':not changes,
            'note':'MP3 decoded to PCM WAV; complete literal references rewritten in staging. Dynamic references are not inferred. Original addon unchanged.'})
    return records
