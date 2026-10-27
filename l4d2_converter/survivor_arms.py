"""Merge native L4D1 arm mappings without replacing unrelated weapon settings."""
from .keyvalues import parse,decode_text,Token,tokens

CHARACTERS={'manager','biker','teengirl','namvet'}
def merge_arm_bindings(base,donor):
    text=decode_text(base);base_tree=parse(text);donor_tree=parse(decode_text(donor))
    def group(tree):
        if len(tree)!=1 or not isinstance(tree[0].value,list):raise ValueError('Expected one weapon definition')
        groups=[e for e in tree[0].value if e.key.value.lower()=='characterviewmodeladdon']
        if len(groups)>1:raise ValueError('Duplicate CharacterViewmodelAddon block')
        if groups and not isinstance(groups[0].value,list):raise ValueError('Expected arm mapping block')
        return groups[0] if groups else None
    source=group(donor_tree);target=group(base_tree)
    if source is None:return base,[]
    mappings=[e for e in source.value if e.key.value.lower() in CHARACTERS and isinstance(e.value,Token)]
    if len({e.key.value.lower() for e in mappings})!=len(mappings):raise ValueError('Duplicate donor survivor arm mapping')
    existing={e.key.value.lower() for e in target.value} if target else set()
    missing=[e for e in mappings if e.key.value.lower() not in existing]
    if not missing:return base,[]
    for e in missing:
        if not e.value.value.lower().replace('\\','/').startswith('models/weapons/arms/') or '"' in e.value.value:
            raise ValueError('Unexpected survivor arm path')
    added=''.join('\n\t\t"'+e.key.value+'" "'+e.value.value.replace('\\','/')+'"' for e in missing)+'\n\t'
    node=target or base_tree[0];depth=0;end=None
    for t in tokens(text):
        if t.start<=node.key.end or t.kind!='brace':continue
        depth+=1 if t.value=='{' else -1
        if depth==0:end=t.start;break
    if end is None:raise ValueError('Unclosed weapon definition')
    if target is None:added='\n\t"CharacterViewmodelAddon"\n\t{'+added+'}\n'
    result=(text[:end]+added+text[end:]).encode('utf-8');parse(decode_text(result))
    return result,[{'character':e.key.value,'model':e.value.value.replace('\\','/')} for e in missing]
