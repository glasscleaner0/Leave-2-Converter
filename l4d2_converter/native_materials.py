"""Read Xbox pooled KeyValues materials without retaining archive pool indices."""
import math,struct
from .formats import unpack_source
from .keyvalues import parse,decode_text

def pool_strings(data):
    data=bytes(unpack_source(data))
    if len(data)<18 or data[4:8]!=b'1PSC':raise ValueError('Unsupported Xbox material string pool')
    pos=14+2*struct.unpack_from('>H',data,12)[0]
    if pos+4>len(data):raise ValueError('Truncated material pool buckets')
    count=struct.unpack_from('>H',data,pos+2)[0];pos+=4;strings=['']
    while pos<len(data):
        if pos+3>=len(data):raise ValueError('Truncated material pool entry')
        pos+=3;end=data.find(b'\0',pos)
        if end<0:raise ValueError('Unterminated material pool entry')
        strings.append(data[pos:end].decode('cp1252'));pos=end+1
    if len(strings)!=count:raise ValueError('Material pool string count mismatch')
    return strings

def material_text(data,pools):
    data=bytes(unpack_source(data))
    if not data.startswith(b'\xaa'):
        parse(decode_text(data));return data
    if len(data)<6 or data[1:5] not in pools:raise ValueError('Native material has no matching string pool')
    strings=pool_strings(pools[data[1:5]]);pos=5;nodes=0
    def take(size):
        nonlocal pos
        if pos+size>len(data):raise ValueError('Truncated native material')
        value=data[pos:pos+size];pos+=size;return value
    def word():
        a,b=struct.unpack('>HH',take(4))
        if max(a,b)>=len(strings):raise ValueError('Material string index outside pool')
        return strings[a]+strings[b]
    def block(depth):
        nonlocal nodes
        if depth>64:raise ValueError('Material nesting limit exceeded')
        result=[]
        while True:
            kind=take(1)[0]
            if kind==11:return result
            nodes+=1
            if nodes>100000:raise ValueError('Material node limit exceeded')
            key=word()
            if kind==0:value=block(depth+1)
            elif kind==1:value=word()
            elif kind==2:value=str(struct.unpack('>i',take(4))[0])
            elif kind==3:
                number=struct.unpack('>f',take(4))[0]
                if not math.isfinite(number):raise ValueError('Nonfinite material number')
                value=format(number,'.9g')
            elif kind==8:value=str(take(1)[0])
            elif kind in (9,10):value=str(kind-9)
            else:raise ValueError('Unsupported native material value type '+str(kind))
            result.append((key,value))
    if take(1)!=b'\0':raise ValueError('Expected native material root')
    shader=word();properties=block(0)
    if pos!=len(data):raise ValueError('Trailing native material data')
    def quote(value):
        if any(c in value for c in ('"','\r','\n','\0')):raise ValueError('Unsupported material text string')
        return '"'+value+'"'
    def emit(key,value,depth=0):
        pad=' '*depth
        if isinstance(value,list):return pad+quote(key)+'\n'+pad+'{\n'+''.join(emit(k,v,depth+1) for k,v in value)+pad+'}\n'
        return pad+quote(key)+' '+quote(value)+'\n'
    result=emit(shader,properties).encode('cp1252');parse(decode_text(result));return result
