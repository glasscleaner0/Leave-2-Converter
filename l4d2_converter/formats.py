"""Original format adapters around the external converter; no SDK source."""
import io
import lzma
import struct
import wave
from .archive import XboxZip, aligned_zip


def unpack_source(data):
    if data[:4] != b'LZMA':
        return data
    if len(data) < 17:
        raise ValueError('Truncated Source LZMA header')
    size, packed = struct.unpack_from('<II', data, 4)
    prop = data[12]
    if size > 256 * 1024 * 1024 or packed + 17 > len(data) or prop >= 225:
        raise ValueError('Invalid Source LZMA sizes/properties')
    dictionary = int.from_bytes(data[13:17], 'little')
    if dictionary > 64 * 1024 * 1024:
        raise ValueError('LZMA dictionary exceeds limit')
    dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[{
        'id': lzma.FILTER_LZMA1, 'dict_size': dictionary,
        'lc': prop % 9, 'lp': (prop // 9) % 5, 'pb': prop // 45}])
    # Source streams are delimited by the header length and may omit an end
    # marker. Padding bits can decode beyond that length, so stop exactly there.
    output = dec.decompress(data[17:17 + packed], max_length=size)
    if len(output) != size:
        raise ValueError('Source LZMA decoded size mismatch')
    return output


def pack_source(data):
    if len(data) < 64:
        return data
    packed = lzma.compress(data, format=lzma.FORMAT_RAW, filters=[{
        'id': lzma.FILTER_LZMA1, 'dict_size': 1 << 20, 'lc': 3, 'lp': 0, 'pb': 2}])
    output = b'LZMA' + struct.pack('<II', len(data), len(packed)) + b'\x5d' + struct.pack('<I', 1 << 20) + packed
    if unpack_source(output) != data:
        raise ValueError('Source compression roundtrip failed')
    return output if len(output) < len(data) else data


def bsp_rows(data):
    if len(data) < 1036 or data[:4] not in (b'VBSP', b'PSBV'):
        raise ValueError('Invalid BSP header')
    endian = '<' if data[:4] == b'VBSP' else '>'
    version = struct.unpack_from(endian + 'I', data, 4)[0]
    if version not in (20, 21):
        raise ValueError(f'BSP version {version} is not supported')
    result = []
    for i in range(64):
        row = struct.unpack_from(endian + '4I', data, 8 + i * 16)
        off, size, ver, uncompressed = row if version == 20 else (row[1], row[2], row[0], row[3])
        if size and (off < 1036 or off + size > len(data)):
            raise ValueError(f'BSP lump {i} is outside file')
        result.append((off, size, ver, uncompressed))
    return result


def bsp_lump(data, index):
    off, size, _, decoded = bsp_rows(data)[index]
    chunk = data[off:off + size]
    if decoded:
        chunk = unpack_source(chunk)
        if len(chunk) != decoded:
            raise ValueError('BSP lump decoded length mismatch')
    return chunk


def sdk_bsp_input(data):
    """Translate the L4D2 v21 directory layout to the SDK's v20 layout.

    This does not downgrade arbitrary geometry. Body/lump bytes and original
    offsets stay identical; unsupported lump contents must still fail conversion.
    """
    if data[:4] != b'VBSP':
        raise ValueError('Expected PC BSP input')
    rows = bsp_rows(data)
    if struct.unpack_from('<I', data, 4)[0] == 20:
        return data
    output = bytearray(data)
    struct.pack_into('<I', output, 4, 20)
    for i, row in enumerate(rows):
        struct.pack_into('<4I', output, 8 + i * 16, *row)
    if output[1036:] != data[1036:] or bsp_rows(output) != rows:
        raise ValueError('BSP input adapter changed body data')
    return bytes(output)


def static_prop_summary(data):
    game = bsp_lump(data, 35)
    endian = '<' if data[:4] == b'VBSP' else '>'
    if len(game) < 4:
        return None
    count = struct.unpack_from(endian + 'I', game)[0]
    if count > 1000 or 4 + count * 16 > len(game):
        raise ValueError('Invalid game-lump directory')
    for i in range(count):
        ident, flags, version, off, size = struct.unpack_from(endian + 'IHHII', game, 4 + i * 16)
        if ident != int.from_bytes(b'sprp', 'big'):
            continue
        payload = game[off:] if endian == '>' else data[off:off + size]
        payload = unpack_source(payload)[:size] if flags else payload[:size]
        if len(payload) != size or size < 4:
            raise ValueError('Invalid static-prop payload')
        models = struct.unpack_from(endian + 'I', payload)[0]
        pos = 4 + models * 128
        if models > 10000 or pos + 4 > size:
            raise ValueError('Invalid static-prop model table')
        names = [payload[4 + j * 128:4 + (j + 1) * 128].split(b'\0')[0].decode('cp1252')
                 for j in range(models)]
        leaves = struct.unpack_from(endian + 'I', payload, pos)[0]
        pos += 4 + leaves * 2
        if pos + 4 > size:
            raise ValueError('Invalid static-prop leaf table')
        instances = struct.unpack_from(endian + 'I', payload, pos)[0]
        return {'version': version, 'models': names, 'leaves': leaves, 'instances': instances, 'bytes': size}
    return None


def pcm_xwv(data):
    """Lossless 16-bit PCM WAV to the Xbox XWV wrapper; bounded format support."""
    with wave.open(io.BytesIO(data)) as reader:
        channels, width, rate, frames = (reader.getnchannels(), reader.getsampwidth(),
                                          reader.getframerate(), reader.getnframes())
        samples = reader.readframes(frames)
    if width != 2 or channels not in (1, 2) or rate not in (11025, 22050, 44100):
        raise ValueError('PCM fallback requires 16-bit mono/stereo WAV at 11025/22050/44100 Hz')
    if len(samples) != frames * width * channels:
        raise ValueError('Truncated WAV sample data')
    loop = -1
    p = 12
    while p + 8 <= len(data):
        tag, size = struct.unpack_from('<4sI', data, p)
        chunk = data[p + 8:p + 8 + size]
        if len(chunk) != size:
            raise ValueError('Truncated WAV chunk')
        if tag == b'smpl':
            if size < 36:
                raise ValueError('Invalid WAV sampler chunk')
            loops = struct.unpack_from('<I', chunk, 28)[0]
            if loops not in (0, 1):
                raise ValueError('Multiple WAV loops are unsupported')
            if loops:
                if size < 60:
                    raise ValueError('Truncated WAV loop')
                _, kind, start, end, fraction, repeats = struct.unpack_from('<6I', chunk, 36)
                if kind or end != frames - 1 or fraction or repeats or start >= frames:
                    raise ValueError('Unsupported WAV loop semantics')
                loop = start
        p += 8 + size + size % 2
    swapped = bytearray(samples)
    swapped[0::2], swapped[1::2] = samples[1::2], samples[0::2]
    header = struct.pack('>7Ii4H8B', 0x58575620, 4, 48, 0, 2048, len(samples), frames,
                         loop, 0, 0, 0, 0, 0, 16, (11025, 22050, 44100).index(rate), channels, 100, 0, 0, 0)
    return header + bytes(2048 - 48) + swapped


def finish_bsp(data, dictionary=None, *, extra_members=None):
    if data[:8] != b'PSBV\0\0\0\x14':
        raise ValueError('SDK did not produce Xbox BSP v20')
    rows = bsp_rows(data)
    pak = XboxZip(bsp_lump(data, 40))
    members = {n: pak.read(n) for n in pak.entries if n != '__preload_section.pre'}
    for name, payload in (extra_members or {}).items():
        if name in members and members[name] != payload:
            raise ValueError('Conflicting recovered embedded asset: '+name)
        validate_asset(name,payload)
        members[name]=payload
    for name in list(members):
        if name.endswith('.wav') and '.360.' not in name:
            target = name[:-4] + '.360.wav'
            if target in members:
                raise ValueError('Conflicting embedded audio outputs')
            members[target] = pcm_xwv(members.pop(name))
        elif name.endswith('.raw') and '.360.' not in name:
            target = name[:-4] + '.360.raw'
            if target in members: raise ValueError('Conflicting embedded color correction outputs')
            members[target] = color_correction(members.pop(name))
        elif name.endswith(('.vtf', '.mdl', '.vvd', '.nav', '.bsp', '.pcf')) and '.360.' not in name:
            raise ValueError(f'SDK retained unconverted embedded asset: {name}')
        elif '.360.' in name:
            validate_asset(name, members[name])
    if dictionary:
        members['stringtable_dictionary_xbox.dct'] = dictionary
    packed = aligned_zip(members)
    output = bytearray(data[:1036])
    for _, index in sorted((r[0], i) for i, r in enumerate(rows) if r[1]):
        off, size, ver, decoded = rows[index]
        chunk = packed if index == 40 else data[off:off + size]
        output.extend(bytes((-len(output)) % (2048 if index == 40 else 4)))
        offset = len(output)
        output.extend(chunk)
        struct.pack_into('>4I', output, 8 + index * 16, offset, len(chunk), ver, 0 if index == 40 else decoded)
    output.extend(bytes((-len(output)) % 2048))
    check = bsp_rows(output)
    for i, (off, size, ver, decoded) in enumerate(rows):
        o2, n2, v2, c2 = check[i]
        if i != 40 and (size, ver, decoded, data[off:off + size]) != (n2, v2, c2, output[o2:o2 + n2]):
            raise ValueError('BSP packaging changed a non-pak lump')
        if n2:
            bsp_lump(output, i)
    return bytes(output)


def validate_asset(name, data):
    plain = unpack_source(data)
    if not plain:
        raise ValueError(f'Empty output: {name}')
    suffix = name.rsplit('.', 1)[-1]
    if suffix == 'raw': color_correction(plain)
    expected = {'vtf': b'VTFX', 'mdl': b'TSDI', 'vvd': b'VSDI',
                'wav': b'XWV ', 'nav': bytes.fromhex('feedface'), 'bsp': b'PSBV'}
    if suffix in expected and plain[:4] != expected[suffix]:
        raise ValueError(f'Wrong console signature: {name}: {plain[:4]!r}')
    if suffix == 'bsp':
        bsp_rows(plain)
    if suffix == 'mdl':
        if len(plain) < 80 or struct.unpack_from('>I', plain, 76)[0] != len(plain):
            raise ValueError(f'Model declared size mismatch: {name}')
    if suffix == 'wav':
        if len(plain) < 48 or struct.unpack_from('>I', plain, 4)[0] != 4:
            raise ValueError('Unsupported XWV header')
        offset, size = struct.unpack_from('>2I', plain, 16)
        if offset + size > len(plain):
            raise ValueError('XWV payload outside file')
    return plain


def color_correction(data):
    # Stock PC and Xbox RAW lookup tables both contain 32^3 RGB byte triplets.
    # Preserve the author's palette; no endian swap or inferred gamma change.
    if len(data) != 32**3*3:
        raise ValueError('Color correction requires a 32x32x32 RGB lookup table (98304 bytes)')
    return data
