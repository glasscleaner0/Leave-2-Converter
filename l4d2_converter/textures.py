"""Independent Xbox texture header reader and size diagnostics."""
import struct
from .formats import unpack_source,bsp_lump
from .archive import XboxZip


def texture_info(data):
    data = unpack_source(data)
    if len(data) < 60 or data[:4] != b'VTFX':
        raise ValueError('Invalid Xbox texture header')
    major, minor, header, flags = struct.unpack_from('>4I', data, 4)
    width, height, depth, frames, preload = struct.unpack_from('>5H', data, 20)
    skip, resources = data[30:32]
    image_format, compressed = struct.unpack_from('>I4xI', data, 48)
    if (major, minor) != (0x360, 8) or not width or not height or not depth or not frames:
        raise ValueError('Unsupported Xbox texture dimensions/version')
    if header < 60 + resources * 8 or header > len(data):
        raise ValueError('Xbox texture resource table outside header')
    image_offset = None
    for i in range(resources):
        tag = data[60+i*8:64+i*8]
        offset = struct.unpack_from('>I', data, 64+i*8)[0]
        if tag[:3] == b'\x30\0\0':
            if tag[3] or not header <= offset < len(data):
                raise ValueError('Xbox texture image resource outside payload')
            image_offset = offset
    if image_offset is None:
        raise ValueError('Xbox texture has no image resource')
    if compressed > len(data) - image_offset:
        raise ValueError('Xbox texture compressed payload outside file')
    # Logical mip-chain size, before GPU tiling/alignment and allocation overhead.
    # Unknown formats remain readable but have no size estimate.
    block = {13: 8, 14: 16, 15: 16, 20: 8, 37: 16, 38: 8}.get(image_format)
    pixel = {0: 4, 1: 4, 2: 3, 3: 3, 4: 2, 5: 1, 6: 2, 8: 1,
             7: 1, 9: 3, 10: 3, 11: 4, 12: 4, 16: 4, 17: 2, 18: 2,
             19: 2, 21: 2, 22: 2, 23: 4, 24: 8, 25: 8, 26: 4,
             27: 4, 28: 12, 29: 16}.get(image_format)
    estimate = 0 if block or pixel else None
    w, h, d = width, height, depth
    while estimate is not None:
        estimate += (((w + 3)//4) * ((h + 3)//4) * block if block else w*h*pixel) * d
        if flags & 0x100 or (w, h, d) == (1, 1, 1):
            break
        w, h, d = max(1,w//2), max(1,h//2), max(1,d//2)
    if estimate is not None:
        estimate *= frames * (6 if flags & 0x4000 else 1)
    return {'width':width, 'height':height, 'depth':depth, 'frames':frames,
            'mip_skip':skip, 'image_format':image_format, 'flags':flags,
            'file_bytes':len(data), 'image_offset':image_offset,
            'compressed_bytes':compressed, 'logical_image_bytes':estimate}


def texture_budget(members, stock_read=None, maps=None):
    rows, warnings = [], []
    map_rows = []
    def add(name,data,container):
        row = {'path':name, 'container':container, **texture_info(data)}
        old = stock_read(name) if stock_read else None
        if old is not None:
            row['stock'] = texture_info(old)
            a, b = row['logical_image_bytes'], row['stock']['logical_image_bytes']
            if a is not None and b is not None:
                row['logical_growth_bytes'] = a-b
        if row['logical_image_bytes'] is not None and row['logical_image_bytes'] >= 8*1024*1024:
            warnings.append(f'{name}: {row["frames"]} frames, {row["logical_image_bytes"]/1048576:.1f} MiB logical texture data before GPU allocation overhead.')
        rows.append(row)
        return row
    for name, data in sorted(members.items()):
        if name.endswith('.360.vtf'): add(name,data,'addon-archive')
    loose_total=sum(r['logical_image_bytes'] or 0 for r in rows)
    for map_name,data in sorted((maps or {}).items()):
        pak=XboxZip(bsp_lump(data,40))
        embedded=[]
        for name in sorted(pak.entries):
            if name.endswith('.360.vtf'): embedded.append(add(name,pak.read(name),map_name))
        map_rows.append({'map':map_name,'embedded_textures':len(embedded),
            'embedded_logical_image_bytes':sum(r['logical_image_bytes'] or 0 for r in embedded),
            'unknown_formats':sum(r['logical_image_bytes'] is None for r in embedded)})
    total = sum(r['logical_image_bytes'] or 0 for r in rows)
    unknown = sum(r['logical_image_bytes'] is None for r in rows)
    if unknown:
        warnings.append(f'{unknown} textures use formats with no size estimate; the total is incomplete. See report.json for their format IDs.')
    if total >= 32*1024*1024:
        warnings.append(f'Packaged textures total {total/1048576:.1f} MiB of logical image data; this is an asset inventory, not measured simultaneous RAM use.')
    return {'textures':rows, 'logical_image_bytes':total,
            'archive_logical_image_bytes':loose_total,'maps':map_rows,
            'unknown_formats':unknown,
            'note':'Inventory includes packaged archive and BSP textures across every chapter, not simultaneous residency. It excludes GPU tiling/alignment, model data, referenced stock textures and engine memory. Actual residency requires console measurement.'}, warnings
