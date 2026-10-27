"""Optional user-supplied addon information, applied only to the staging copy."""
from pathlib import Path
from .loader import addon_metadata
from .keyvalues import parse,decode_text,Token

FIELDS=('addontitle','addondescription','addonauthor')
LABELS={'addontitle':'Name','addondescription':'Description','addonauthor':'Author'}

def prepare_addon_info(game,input_path,prompt=None,cancelled=lambda:False):
    path=Path(game)/'addoninfo.txt';original=path.read_bytes() if path.is_file() else None
    fallback=Path(input_path).stem
    fields,warnings=addon_metadata(original,fallback)
    existing={}
    if original:
        try:
            roots=parse(decode_text(original))
            existing={e.key.value.lower():e.value.value for e in roots[0].value if isinstance(e.value,Token)} if len(roots)==1 and roots[0].key.value.casefold()=='addoninfo' and isinstance(roots[0].value,list) else {}
        except ValueError:pass
    missing=[key for key in FIELDS if not existing.get(key,'').strip()]
    title=existing.get('addontitle','').strip()
    if title.isdecimal() and 'addontitle' not in missing:missing.insert(0,'addontitle')
    report={'status':'unchanged','missing_fields':missing,'warnings':warnings,'source_modified':False}
    if not missing:return report
    if cancelled():raise InterruptedError('Conversion cancelled')
    initial={key:fields.get(key,'') for key in FIELDS}
    if initial['addontitle'].strip().isdecimal():initial['addontitle']=''
    if prompt is None:report['status']='needs-info-no-prompt';return report
    answer=prompt({'fields':initial,'missing_fields':missing,'input_name':Path(input_path).name,'warnings':warnings})
    if cancelled():raise InterruptedError('Conversion cancelled')
    if answer is None:report['status']='declined';return report
    values={key:str(answer.get(key,initial[key])).replace('\r\n','\n').replace('\r','\n').strip() for key in FIELDS}
    if not values['addontitle'] or values['addontitle'].isdecimal():raise ValueError('Addon name must contain a descriptive name, not only a Workshop ID')
    for key,value in values.items():
        if len(value)>(4096 if key=='addondescription' else 256):raise ValueError(LABELS[key]+' is too long')
        if any(ord(c)<32 and not (key=='addondescription' and c in '\n\t') for c in value):raise ValueError(LABELS[key]+' contains unsupported control characters')
    # Keep original scalar metadata/content flags. Match the Loader's established
    # quote handling so user-entered text cannot become new KeyValues fields.
    fields={**existing,**fields,**values}
    def clean(value):return str(value).replace('"',"'").replace('\0','')
    text='"AddonInfo"\n{\n'+''.join(' "'+key+'" "'+clean(value)+'"\n' for key,value in fields.items())+'}\n'
    parse(text);path.write_text(text,encoding='utf-8')
    report.update(status='manual-info-applied',fields={key:clean(value) for key,value in values.items()})
    return report
