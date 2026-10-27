"""Small independent KeyValues text reader and non-destructive mission adapter."""
from dataclasses import dataclass
import re


def decode_text(data):
    if isinstance(data, str):
        return data
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        # Legacy addon files use Windows text bytes, including undefined C1
        # bytes. Preserve those bytes rather than rejecting unrelated comments.
        return data.decode('cp1252', errors='surrogateescape')


@dataclass
class Token:
    value: str
    start: int
    end: int
    kind: str


@dataclass
class Entry:
    key: Token
    value: object


class KeyValuesSyntaxError(ValueError):
    def __init__(self, message, text, position):
        self.position=position
        self.line=text.count('\n',0,position)+1
        previous=text.rfind('\n',0,position)
        self.column=position-previous
        self.reason=message
        super().__init__(f'{message} (line {self.line}, column {self.column})')


def tokens(text,escape_sequences=False):
    result = []
    pos = 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        if text.startswith('//', pos):
            end = text.find('\n', pos)
            pos = len(text) if end < 0 else end + 1
            continue
        if text.startswith('/*', pos):
            end = text.find('*/', pos + 2)
            if end < 0: raise KeyValuesSyntaxError('Unterminated KeyValues comment',text,pos)
            pos = end + 2
            continue
        start = pos
        if text[pos] == '"':
            pos += 1
            value = []
            while pos < len(text) and text[pos] != '"':
                if escape_sequences and text[pos] == '\\' and pos + 1 < len(text) and text[pos + 1] in ('"', '\\'):
                    pos += 1
                value.append(text[pos])
                pos += 1
            if pos == len(text): raise KeyValuesSyntaxError('Unterminated KeyValues string',text,start)
            pos += 1
            result.append(Token(''.join(value), start, pos, 'string'))
        elif text[pos] in '{}':
            result.append(Token(text[pos], pos, pos + 1, 'brace'))
            pos += 1
        else:
            while pos < len(text) and not text[pos].isspace() and text[pos] not in '{}"': pos += 1
            result.append(Token(text[start:pos], start, pos, 'bare'))
    return result


def parse(text):
    ts = tokens(text)
    def block(pos, nested=False, opening=None):
        entries = []
        while pos < len(ts):
            key = ts[pos]
            if key.kind == 'brace':
                if key.value == '}' and nested: return entries, pos + 1
                raise KeyValuesSyntaxError('Unexpected KeyValues brace',text,key.start)
            if key.value.startswith('[') and key.value.endswith(']'):
                pos += 1
                continue
            if pos + 1 >= len(ts): raise KeyValuesSyntaxError('KeyValues key has no value: '+key.value,text,key.start)
            value = ts[pos + 1]
            if value.kind == 'brace':
                if value.value != '{': raise KeyValuesSyntaxError('KeyValues key has no value: '+key.value,text,key.start)
                children, pos = block(pos + 2, True, value)
                entries.append(Entry(key, children))
            else:
                entries.append(Entry(key, value))
                pos += 2
        if nested: raise KeyValuesSyntaxError('Unclosed KeyValues block: opening brace has no closing brace',text,opening.start)
        return entries, pos
    return block(0)[0]


def leaf_pairs(data):
    # Dependency discovery remains permissive about EOF/extra braces, as the
    # previous reader was. Mission editing uses the strict tree parser instead.
    ts=[]
    # Source KeyValues files commonly disable escape sequences: a quoted
    # directory can legitimately end in a backslash immediately before '"'.
    # Keep discovery as tolerant as the original reader about malformed tails.
    text=decode_text(data)
    for m in re.finditer(r'"([^"\r\n]*)"|(//[^\r\n]*|/\*[\s\S]*?\*/)|([^\s{}"]+)|([{}])',text):
        if m.group(2) is None:
            value=m.group(1) if m.group(1) is not None else m.group(3) or m.group(4)
            ts.append(Token(value,m.start(),m.end(),'brace' if m.group(4) else 'string'))
    result = []
    def walk(pos):
        while pos < len(ts):
            key=ts[pos]
            if key.kind == 'brace':
                if key.value == '}': return pos+1
                pos=walk(pos+1)
                continue
            if key.value.startswith('['):
                pos+=1
                continue
            if pos+1 >= len(ts): return len(ts)
            value=ts[pos+1]
            pos+=2
            if value.kind == 'brace':
                if value.value=='{': pos=walk(pos)
            else: result.append((key.value.lower(),value.value))
        return pos
    walk(0)
    return result


def prepare_mission(data):
    """Edit only mission-root Xbox fields; retain comments and nested blocks."""
    text = decode_text(data)
    root = parse(text)
    if len(root) != 1 or not isinstance(root[0].value, list):
        raise ValueError('Mission must contain one root block')
    fields = root[0].value
    names = [e.value.value for e in fields if e.key.value.lower() == 'name' and isinstance(e.value, Token)]
    if len(names) != 1 or not re.fullmatch(r'[a-zA-Z0-9_-]+', names[0]):
        raise ValueError('Missing/unsafe/duplicate mission identifier')
    edits = []
    for e in fields:
        if e.key.value.lower() in ('builtin', 'x360ctx', 'dlcmask'):
            if not isinstance(e.value, Token): raise ValueError('Xbox mission field must be a scalar')
            edits.append((e.key.start,e.value.end,''))
    # Locate the actual root opening token, not a brace in a leading comment.
    opening = next(t for t in tokens(text) if t.kind == 'brace' and t.value == '{')
    edits.append((opening.end,opening.end,'\n\t"BuiltIn" "0"\n\t"x360ctx" "16"\n\t"dlcmask" "0x0000000000000000"\n'))
    for start,end,value in sorted(edits,reverse=True): text = text[:start]+value+text[end:]
    parse(text)
    # UTF-8 input stays UTF-8; surrogateescaped legacy bytes stay byte-exact.
    encoding = 'cp1252' if any(0xdc80 <= ord(c) <= 0xdcff for c in text) else ('utf-8' if _utf8(data) else 'cp1252')
    return names[0], text.encode(encoding,errors='surrogateescape')


def mission_maps(data):
    root = parse(decode_text(data))
    if len(root) != 1 or not isinstance(root[0].value,list): raise ValueError('Mission must contain one root block')
    result = []
    def walk(entries):
        for e in entries:
            if isinstance(e.value,list): walk(e.value)
            elif e.key.value.lower() == 'map':
                name=e.value.value.replace('\\','/').lower()
                if not re.fullmatch(r'[a-z0-9_+&/-]+',name) or any(p in ('', '.', '..') for p in name.split('/')):
                    raise ValueError('Unsafe mission map name: ' + name)
                if name not in result: result.append(name)
    for e in root[0].value:
        if e.key.value.lower() == 'modes' and isinstance(e.value,list): walk(e.value)
    return result


def mission_modes(data):
    root = parse(decode_text(data))
    if len(root) != 1 or not isinstance(root[0].value, list):
        raise ValueError('Mission must contain one root block')
    return list(dict.fromkeys(mode.key.value.lower() for entry in root[0].value
        if entry.key.value.lower() == 'modes' and isinstance(entry.value, list)
        for mode in entry.value if isinstance(mode.value, list)))


def survival_mission(identifier, maps):
    """Generate registration metadata only; map gameplay remains unmodified."""
    if not maps:
        raise ValueError('Survival mission needs at least one map')
    rows = []
    for i, name in enumerate(dict.fromkeys(maps), 1):
        # Use the same restricted names as mission_maps before interpolation.
        if not re.fullmatch(r'[a-z0-9_+&/-]+',name) or any(p in ('', '.', '..') for p in name.split('/')):
            raise ValueError('Unsafe mission map name: ' + name)
        rows.append(f'"{i}" {{ "Map" "{name}" "DisplayName" "{name}" }}')
    if not re.fullmatch(r'[a-zA-Z0-9]+',identifier):
        raise ValueError('Unsafe mission identifier')
    source = ('"mission" { "Name" "'+identifier+'" "Version" "1" '
        '"DisplayTitle" "'+maps[0]+'" "modes" { "survival" { '+'\n'.join(rows)+' } } }').encode('utf8')
    return prepare_mission(source)


def _utf8(data):
    try:
        data.decode('utf-8-sig')
        return True
    except UnicodeDecodeError: return False
