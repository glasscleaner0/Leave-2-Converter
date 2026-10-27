"""Independent VPK reader and aligned Xbox ZIP writer; standard library only."""
import io
import re
import struct
import zipfile
import zlib
from pathlib import Path, PurePosixPath


def safe_name(name):
    name = name.replace('\\', '/').lower()
    p = PurePosixPath(name)
    if not name or p.is_absolute() or any(x in ('', '.', '..') for x in name.split('/')):
        raise ValueError(f'Unsafe archive path: {name!r}')
    if any(c in name for c in ':<>"|?*\0') or any(ord(c) < 32 for c in name):
        raise ValueError(f'Unsafe archive path: {name!r}')
    if any(part.rstrip(' .') != part or part.split('.')[0].upper() in
           {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
            *(f'LPT{i}' for i in range(1, 10))} for part in p.parts):
        raise ValueError(f'Unsafe Windows path: {name!r}')
    return name


class Vpk:
    def __init__(self, path):
        self.path = Path(path)
        with self.path.open('rb') as f:
            header = f.read(28)
            if len(header) < 12:
                raise ValueError('Truncated VPK header')
            magic, version, tree_size = struct.unpack_from('<3I', header)
            if magic != 0x55AA1234 or version not in (1, 2):
                raise ValueError('Only VPK version 1 and 2 are supported')
            self.header_size = 12 if version == 1 else 28
            if tree_size > 64 * 1024 * 1024 or self.header_size + tree_size > self.path.stat().st_size:
                raise ValueError('Invalid VPK directory size')
            f.seek(self.header_size)
            tree = f.read(tree_size)
        self.data_start = self.header_size + tree_size
        self.data_size = (self.path.stat().st_size - self.data_start if version == 1
                          else struct.unpack_from('<I', header, 12)[0])
        if self.data_start + self.data_size > self.path.stat().st_size:
            raise ValueError('Invalid VPK data section size')
        pos = 0
        self.entries = {}

        def word():
            nonlocal pos
            end = tree.find(b'\0', pos)
            if end < 0:
                raise ValueError('Unterminated VPK directory string')
            value = tree[pos:end].decode('latin1')
            pos = end + 1
            return value

        while extension := word():
            while folder := word():
                while stem := word():
                    if pos + 18 > len(tree):
                        raise ValueError('Truncated VPK entry')
                    crc, preload, archive, offset, size, terminator = struct.unpack_from('<IHHIIH', tree, pos)
                    pos += 18
                    if terminator != 65535 or pos + preload > len(tree):
                        raise ValueError('Invalid VPK entry')
                    raw_name = ('' if folder == ' ' else folder + '/') + stem + ('' if extension == ' ' else '.' + extension)
                    # Some Workshop archives contain redundant internal separators.
                    # Normalize only those; retain absolute/traversal rejection and
                    # reject aliases that collide after normalization.
                    raw_name = raw_name.replace('\\', '/')
                    if raw_name.startswith('/') or raw_name.endswith('/'):
                        raise ValueError(f'Unsafe archive path: {raw_name!r}')
                    name = safe_name(re.sub('/+', '/', raw_name))
                    if name in self.entries:
                        raise ValueError(f'Duplicate VPK path: {name}')
                    self.entries[name] = (crc, tree[pos:pos + preload], archive, offset, size)
                    pos += preload
        if pos != len(tree):
            raise ValueError('Trailing VPK directory bytes')

    def read(self, name):
        crc, preload, archive, offset, size = self.entries[name]
        if size > 512 * 1024 * 1024:
            raise ValueError(f'Asset exceeds 512 MiB limit: {name}')
        path = self.path
        if archive == 32767:
            if offset + size > self.data_size:
                raise ValueError(f'VPK entry outside data section: {name}')
            offset += self.data_start
        elif size:
            if not path.name.lower().endswith('_dir.vpk'):
                raise ValueError('Chunked VPK must use a _dir.vpk directory file')
            path = path.with_name(path.name[:-8] + f'_{archive:03d}.vpk')
        if size:
            if offset + size > path.stat().st_size:
                raise ValueError(f'VPK entry outside archive: {name}')
            with path.open('rb') as f:
                f.seek(offset)
                data = preload + f.read(size)
        else:
            data = preload
        if len(data) != len(preload) + size or zlib.crc32(data) & 0xFFFFFFFF != crc:
            raise ValueError(f'VPK CRC/length mismatch: {name}')
        return data


class XboxZip:
    """Read stored/deflated Source ZIPs, including stock XZP2 central headers."""
    def __init__(self, source):
        self.path = Path(source) if isinstance(source, (str, Path)) else None
        self.data = None if self.path else bytes(source)
        total = self.path.stat().st_size if self.path else len(self.data)
        tail_size = min(total, 65557)
        tail = self.readat(total - tail_size, tail_size)
        end = tail.rfind(b'PK\x05\x06')
        if end < 0 or end + 22 > len(tail):
            raise ValueError('Missing ZIP end record')
        disk, central_disk, count_disk, count, length, offset, comment = struct.unpack_from('<4H2IH', tail, end + 4)
        if disk or central_disk or count_disk != count or offset + length > total:
            raise ValueError('Unsupported ZIP layout')
        self.entries = {}
        self.duplicates = []
        position = 0
        seen = 0
        while position + 30 <= offset:
            localheader = self.readat(position, 30)
            if localheader[:4] != b'PK\x03\x04':
                break
            _, _, flags, method, _, _, crc, packed, size, nl, el = struct.unpack('<I5H3I2H', localheader)
            if flags & 9 or method not in (0, 8):
                raise ValueError('Unsupported ZIP flags/compression')
            payload = position + 30 + nl + el
            if payload + packed > offset:
                raise ValueError('ZIP payload outside local-file section')
            name = safe_name(self.readat(position + 30, nl).decode('cp437'))
            if name in self.entries:
                self.duplicates.append(name)
            self.entries[name] = (payload, packed, size, method, crc)
            seen += 1
            position = payload + packed
        if seen != count:
            raise ValueError('ZIP local-file count differs from end record')
        if position < offset and any(self.readat(position, offset - position)):
            raise ValueError('Unexpected bytes before ZIP directory')

    def readat(self, offset, size):
        if self.path:
            with self.path.open('rb') as f:
                f.seek(offset)
                return f.read(size)
        return self.data[offset:offset + size]

    def read(self, name):
        offset, packed, size, method, crc = self.entries[name]
        if size > 512 * 1024 * 1024:
            raise ValueError('ZIP asset exceeds limit')
        data = self.readat(offset, packed)
        if method == 8:
            dec = zlib.decompressobj(-15)
            data = dec.decompress(data, size + 1)
            if not dec.eof or dec.unconsumed_tail:
                raise ValueError('Invalid compressed ZIP asset')
        if len(data) != size or zlib.crc32(data) & 0xFFFFFFFF != crc:
            raise ValueError(f'ZIP CRC/length mismatch: {name}')
        return data


def aligned_zip(members):
    members = {safe_name(n): b for n, b in members.items() if n != '__preload_section.pre'}
    count = len(members) + 1
    members['__preload_section.pre'] = struct.pack('>4I', 3, count, 0, 2048) + b'\xff\xff' * count
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED, allowZip64=False) as z:
        z.comment = b'XZP1 2048' + bytes(23)
        for name, data in sorted(members.items()):
            if not name.isascii():
                raise ValueError(f'Xbox ZIP names must be ASCII: {name}')
            entry = zipfile.ZipInfo(name, (2009, 10, 6, 0, 0, 0))
            entry.create_system = 0
            entry.create_version = entry.extract_version = 10
            padding = (-(stream.tell() + 30 + len(name))) % 2048
            if 0 < padding < 4:
                padding += 2048
            if padding:
                entry.extra = struct.pack('<HH', 65535, padding - 4) + bytes(padding - 4)
            z.writestr(entry, data)
    result = stream.getvalue()
    check = XboxZip(result)
    for name, data in members.items():
        if check.entries[name][0] % 2048 or check.read(name) != data:
            raise ValueError(f'ZIP verification failed: {name}')
    return result
