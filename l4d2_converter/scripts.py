"""Thin-ICE decoding for L4D2 .nuc scripts.

Python implementation of Matthew Kwan's public-domain ICE algorithm. The
algorithm constants and public-domain reference are attributed in NOTICE.md.
No MakeGameData/Valve SDK implementation code is included.
"""
from functools import lru_cache
import struct

MOD = ((333,313,505,369),(379,375,319,391),(361,445,451,397),(397,425,395,505))
XOR = ((0x83,0x85,0x9b,0xcd),(0xcc,0xa7,0xad,0x41),(0x4b,0x2e,0xd4,0x33),(0xea,0xcb,0x2e,4))
PERM = (0,7,10,13,19,21,24,30,3,5,8,14,16,23,26,29,2,4,9,15,17,22,27,28,1,6,11,12,18,20,25,31)


def multiply(a, b, modulus):
    result = 0
    for bit in range(8):
        if b & (1 << bit):
            result ^= a
        a <<= 1
        if a & 256:
            a ^= modulus
    return result


@lru_cache(maxsize=1)
def boxes():
    result = []
    for box in range(4):
        values = []
        for index in range(1024):
            row = (index & 1) | ((index >> 8) & 2)
            value = ((index >> 1) & 255) ^ XOR[box][row]
            square = multiply(value, value, MOD[box][row])
            fourth = multiply(square, square, MOD[box][row])
            seventh = multiply(multiply(fourth, square, MOD[box][row]), value, MOD[box][row])
            shifted = seventh << (24 - 8 * box)
            values.append(sum(1 << PERM[i] for i in range(32) if shifted & (1 << i)))
        result.append(values)
    return result


def schedule(key):
    if len(key) != 8:
        raise ValueError('Thin-ICE requires an eight-byte key')
    words = list(reversed(struct.unpack('>4H', key)))
    keys = []
    for rotation in (0,1,2,3,2,1,3,0):
        parts = [0,0,0]
        for step in range(15):
            for lane in range(4):
                index = (rotation + lane) % 4
                bit = words[index] & 1
                parts[step % 3] = (parts[step % 3] << 1) | bit
                words[index] = (words[index] >> 1) | ((1 - bit) << 15)
        keys.append(parts)
    return keys


def round_value(value, key):
    left = ((value >> 16) & 1023) | (((value >> 14) | (value << 18)) & 0xffc00)
    right = (value & 1023) | ((value << 2) & 0xffc00)
    exchange = (left ^ right) & key[2]
    left = (left ^ exchange) ^ key[0]
    right = (right ^ exchange) ^ key[1]
    s = boxes()
    return s[0][left >> 10] | s[1][left & 1023] | s[2][right >> 10] | s[3][right & 1023]


def transform(data, key=b'SDhfi878', decrypt=True):
    keys = schedule(key)
    order = range(7, -1, -1) if decrypt else range(8)
    output = bytearray(data)
    for offset in range(0, len(data) - 7, 8):
        left, right = struct.unpack_from('>2I', data, offset)
        for index in order:
            left, right = right, left ^ round_value(right, keys[index])
        struct.pack_into('>2I', output, offset, right, left)
    return bytes(output)


def decode_script(data):
    if not data or len(data) > 1024 * 1024:
        raise ValueError('Invalid encrypted script size')
    result = transform(data)
    if transform(result, decrypt=False) != data:
        raise ValueError('Script encryption roundtrip failed')
    # Valve-encrypted scripts can carry up to one ICE block of trailing NUL padding.
    result = result.rstrip(b'\0')
    text = result.decode('utf8')
    # Valve scripts use ESC as an entity-I/O field separator inside strings.
    # Preserve it byte-exact, but never accept control bytes as executable syntax.
    import re
    allowed_esc = set()
    for match in re.finditer(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"', text, re.S):
        if match.group().startswith('"'):
            allowed_esc.update(match.start()+i for i,c in enumerate(match.group()) if c == '\x1b')
    if any(ord(c) < 32 and c not in '\r\n\t' and not (c == '\x1b' and i in allowed_esc)
           for i,c in enumerate(text)):
        raise ValueError('Decoded script is not valid text; unsupported key/format')
    return result


def literal_script_includes(data):
    """Find literal IncludeScript calls, excluding comments and quoted examples.

    Dynamic expressions remain outside static dependency discovery.
    """
    import re
    text=data.decode('utf-8-sig')
    lex=re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|[A-Za-z_][A-Za-z_0-9]*|[^\s]',re.S)
    ts=[m.group() for m in lex.finditer(text) if not m.group().startswith(('//','/*'))]
    found=[]
    for i,t in enumerate(ts[:-3]):
        if t!='IncludeScript' or ts[i+1]!='(' or not ts[i+2].startswith('"') or ts[i+3] not in (',',')'):continue
        value=ts[i+2][1:-1]
        if '\\' in value:raise ValueError('Escaped IncludeScript paths are unsupported')
        if value not in found:found.append(value)
    return found

