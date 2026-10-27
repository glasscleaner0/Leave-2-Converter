"""Explicit L4D1 mission metadata and the offline crew support requirement."""
from .keyvalues import parse,decode_text,Token

CREW='Leave 2 Loader - L4D1 Survivors'
OFFLINE='Offline Xbox DLC'
NOTE='Offline play with L4D1 survivors requires the L4D1 Survivor Support addon unless the original Xbox DLC is mounted normally. Load the crew patch after Offline Xbox DLC and before custom replacements.'

def requires_l4d1(data):
    # This is a metadata hint, not a replacement for the pipeline's mission
    # syntax validation. An unreadable definition cannot establish this flag.
    try:roots=parse(decode_text(data))
    except (ValueError,UnicodeError):return False
    if len(roots)!=1 or not isinstance(roots[0].value,list):return False
    return any(e.key.value.lower()=='survivor_set' and isinstance(e.value,Token) and e.value.value.strip()=='1' for e in roots[0].value)

def require_crew_enabled(data):
    """Enable only the explicitly required companion, preserving other choices."""
    text=decode_text(data);roots=parse(text)
    if len(roots)!=1 or not isinstance(roots[0].value,list):raise ValueError('Expected AddonList')
    fields=[e for e in roots[0].value if e.key.value.casefold()==CREW.casefold()]
    if len(fields)!=1 or not isinstance(fields[0].value,Token):raise ValueError('Required crew support is not registered')
    value=fields[0].value
    if value.value=='1':return data
    if value.value!='0':raise ValueError('Invalid crew support enabled state')
    return (text[:value.start]+'"1"'+text[value.end:]).encode('utf-8')
