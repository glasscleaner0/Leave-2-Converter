"""Optional console HDR layout adapter; independently written, no SDK code."""
import struct
from .formats import bsp_rows, bsp_lump, sdk_bsp_input, pack_source


def selected_lumps(source):
    if source[:4] != b'VBSP':
        raise ValueError('HDR adapter requires a PC BSP')
    return (58, 53, 54, 51, 55) if bsp_lump(source, 53) else (7, 8, 15, 52, 56)


def append_lumps(data, replacements):
    # Append instead of moving any game-lump data containing internal offsets.
    rows = bsp_rows(data)
    endian = '<' if data[:4] == b'VBSP' else '>'
    version = struct.unpack_from(endian + 'I', data, 4)[0]
    out = bytearray(data)
    for index, (chunk, lump_version, decoded) in replacements.items():
        out.extend(bytes((-len(out)) % 4))
        offset = len(out) if chunk else 0
        out.extend(chunk)
        row = (offset, len(chunk), lump_version, decoded)
        if version == 21:
            row = (lump_version, offset, len(chunk), decoded)
        struct.pack_into(endian + '4I', out, 8 + index * 16, *row)
    for i in range(64):
        if i not in replacements and bsp_lump(out, i) != bsp_lump(data, i):
            raise ValueError(f'HDR adapter changed unrelated lump {i}')
    return bytes(out)


def prepare_hdr_input(source):
    selected = selected_lumps(source)
    rows = bsp_rows(source)
    replacements = {target: (bsp_lump(source, origin), rows[origin][2], 0)
                    for target, origin in zip((7, 8, 15, 52, 56), selected)}
    return sdk_bsp_input(append_lumps(source, replacements))


def retain_hdr(console, source):
    if console[:4] != b'PSBV':
        raise ValueError('HDR adapter requires a converted Xbox BSP')
    faces, lighting, world, indices, ambient = selected_lumps(source)
    if not bsp_lump(source, lighting):
        return console, {'mode': 'no-baked-lighting', 'changed': False}
    if bsp_lump(console, 8) != bsp_lump(source, lighting):
        raise ValueError('SDK lightmap data differs from selected source lighting')
    for target, origin in ((7, faces), (15, world)):
        if len(bsp_lump(console, target)) != len(bsp_lump(source, origin)):
            raise ValueError('SDK lighting structure size differs from source')
    index_data = bsp_lump(source, indices)
    samples = bsp_lump(source, ambient)
    if len(index_data) % 4 or len(samples) % 28:
        raise ValueError('Unsupported ambient lighting record layout')
    leaf_data = bsp_lump(source, 10)
    if bsp_rows(source)[10][2] != 1 or len(leaf_data) % 32 or len(index_data) != len(leaf_data) // 32 * 4:
        raise ValueError('Unsupported leaf layout for HDR ambient indices')
    count = len(samples) // 28
    for pos in range(0, len(index_data), 4):
        n, first = struct.unpack_from('<HH', index_data, pos)
        if n and first + n > count:
            raise ValueError('Ambient index references absent samples')
    swapped = b''.join(index_data[i:i+2][::-1] for i in range(0, len(index_data), 2))
    rows = bsp_rows(console)
    replacements = {}
    for target, origin in ((58, 7), (53, 8), (54, 15)):
        off, size, ver, decoded = rows[origin]
        replacements[target] = (console[off:off+size], ver, decoded)
        replacements[origin] = (b'', 0, 0)
    for index, plain in ((51, swapped), (55, samples)):
        packed = pack_source(plain)
        replacements[index] = (packed, 0 if index == 51 else 1, len(plain) if packed != plain else 0)
    result = append_lumps(console, replacements)
    if bsp_lump(result, 55) != samples or bsp_lump(result, 51) != swapped:
        raise ValueError('HDR ambient preservation verification failed')
    return result, {'mode': 'retain-source-hdr' if lighting == 53 else 'standard-lighting-to-console-hdr',
                    'changed': True, 'ambient_samples': count, 'ambient_indices': len(index_data)//4,
                    'hardware_tested': False}
