import io
import struct
import tempfile
import unittest
import wave
import zlib
from pathlib import Path
from l4d2_converter.archive import Vpk, XboxZip, aligned_zip, safe_name
from l4d2_converter.dependencies import pairs
from l4d2_converter.formats import sdk_bsp_input, bsp_rows, pcm_xwv, pack_source, unpack_source
from l4d2_converter.scripts import transform


def vpk_bytes(name='asset', payload=b'example', version=1, archive=32767, preload=b''):
    tree = b'txt\0folder\0' + name.encode() + b'\0'
    tree += struct.pack('<IHHIIH', zlib.crc32(preload + payload), len(preload), archive, 0, len(payload), 65535)
    tree += preload + b'\0\0\0'
    header = struct.pack('<3I', 0x55aa1234, version, len(tree))
    if version == 2:
        header += struct.pack('<4I', len(payload) if archive == 32767 else 0, 0, 0, 0)
    return header + tree + (payload if archive == 32767 else b'')


class Formats(unittest.TestCase):
    def test_unsafe_paths(self):
        for name in ('../escape', '/absolute', 'a/../../b', 'C:/file', 'a//b', 'a/CON.txt', 'name. ', 'a\\..\\b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_name(name)

    def test_vpk_versions_preload_and_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for version in (1, 2):
                p = root / 'item.vpk'
                p.write_bytes(vpk_bytes(version=version, preload=b'pre'))
                self.assertEqual(Vpk(p).read('folder/asset.txt'), b'preexample')
            p = root / 'item_dir.vpk'
            p.write_bytes(vpk_bytes(version=2, archive=0))
            (root / 'item_000.vpk').write_bytes(b'example')
            self.assertEqual(Vpk(p).read('folder/asset.txt'), b'example')

    def test_vpk_crc_and_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'bad.vpk'
            p.write_bytes(vpk_bytes()[:-1] + b'!')
            with self.assertRaises(ValueError):
                Vpk(p).read('folder/asset.txt')
            p.write_bytes(vpk_bytes(name='../../bad'))
            with self.assertRaises(ValueError):
                Vpk(p)

    def test_vpk_redundant_internal_separators(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'addon.vpk'
            p.write_bytes(vpk_bytes(name='nested//asset'))
            self.assertEqual(Vpk(p).read('folder/nested/asset.txt'),b'example')
            for name in ('../bad','nested//../bad'):
                p.write_bytes(vpk_bytes(name=name))
                with self.assertRaises(ValueError):Vpk(p)

    def test_zip_alignment_crc(self):
        members = {'materials/test.vmt': b'hello', 'scripts/test.nut': b'world'}
        data = aligned_zip(members)
        archive = XboxZip(data)
        for name, payload in members.items():
            self.assertEqual(archive.read(name), payload)
            self.assertEqual(archive.entries[name][0] % 2048, 0)
        altered = bytearray(data)
        altered[archive.entries['materials/test.vmt'][0]] ^= 1
        with self.assertRaises(ValueError):
            XboxZip(altered).read('materials/test.vmt')

    def test_bsp_adapter_preserves_body(self):
        data = bytearray(1040)
        data[:8] = b'VBSP' + struct.pack('<I', 21)
        struct.pack_into('<4I', data, 8, 0, 1036, 4, 0)
        data[1036:] = b'test'
        adapted = sdk_bsp_input(data)
        self.assertEqual(adapted[1036:], b'test')
        self.assertEqual(bsp_rows(adapted), bsp_rows(data))
        struct.pack_into('<I', data, 12, 9000)
        with self.assertRaises(ValueError):
            sdk_bsp_input(data)

    def test_source_compression(self):
        payload = bytes(range(256)) * 100
        self.assertEqual(unpack_source(pack_source(payload)), payload)
        with self.assertRaises(ValueError):
            unpack_source(b'LZMA')

    def test_pcm_samples_are_lossless(self):
        samples = struct.pack('<4h', -32768, -1, 0, 32767)
        stream = io.BytesIO()
        with wave.open(stream, 'wb') as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(22050)
            writer.writeframes(samples)
        output = pcm_xwv(stream.getvalue())
        self.assertEqual(output[:4], b'XWV ')
        self.assertEqual(output[2048:], struct.pack('>4h', -32768, -1, 0, 32767))

    def test_ice_roundtrip_and_tail(self):
        data = b'0123456789abcdefTAIL'
        cipher = transform(data, decrypt=False)
        self.assertEqual(transform(cipher), data)
        self.assertEqual(cipher[-4:], b'TAIL')
        self.assertNotEqual(cipher[:16], data[:16])

    def test_material_proxy_is_not_texture_reference(self):
        data = b'"Shader" { "$basetexture" "user/block" "Proxies" { "ToggleTexture" { "toggleTextureVar" "$basetexture" "toggleTextureFrameNumVar" "$frame" } } }'
        settings = pairs(data)
        self.assertEqual([value for key, value in settings if key == '$basetexture'], ['user/block'])


if __name__ == '__main__':
    unittest.main()
