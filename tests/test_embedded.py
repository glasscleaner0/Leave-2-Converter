import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from test_loading import texture
from l4d2_converter.archive import XboxZip, aligned_zip
from l4d2_converter.formats import bsp_lump, finish_bsp
from l4d2_converter.embedded import missing_embedded_textures, recover_embedded_textures


def bsp(entries, console=False):
    endian='>' if console else '<'
    data=bytearray(1036);data[:4]=b'PSBV' if console else b'VBSP'
    struct.pack_into(endian+'I',data,4,20)
    for index,payload in ((0,b'entities'),(40,aligned_zip(entries))):
        struct.pack_into(endian+'4I',data,8+index*16,len(data),len(payload),0,0);data.extend(payload)
    return bytes(data)


def pc_texture():
    data=bytearray(80);data[:4]=b'VTF\0';struct.pack_into('<I',data,20,0x4000);struct.pack_into('<H',data,24,1)
    return bytes(data)


class Embedded(unittest.TestCase):
    def test_distinct_ldr_hdr_inventory_and_no_repeat_for_existing(self):
        source=bsp({'materials/maps/m/cubemapdefault.vtf':pc_texture(),'materials/maps/m/cubemapdefault.hdr.vtf':pc_texture()})
        console=bsp({'materials/maps/m/cubemapdefault.hdr.360.vtf':texture(flags=0x4000)},True)
        missing=missing_embedded_textures(source,console)
        self.assertEqual(set(missing),{'materials/maps/m/cubemapdefault.vtf'})
        self.assertFalse(missing_embedded_textures(source,bsp({'materials/maps/m/cubemapdefault.360.vtf':texture(),'materials/maps/m/cubemapdefault.hdr.360.vtf':texture()},True)))

    def test_recovery_uses_source_bytes_and_preserves_existing_assets_and_lumps(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload=pc_texture();source=bsp({'materials/maps/m/cubemapdefault.vtf':payload})
            hdr=texture(flags=0x4000);console=bsp({'materials/maps/m/cubemapdefault.hdr.360.vtf':hdr},True)
            backend=SimpleNamespace(game=Path(tmp))
            def run(name,expected):
                self.assertEqual((backend.game/name).read_bytes(),payload)
                return {expected[0]:texture(flags=0x4000)}
            backend.run=run
            recovered,records=recover_embedded_textures(source,console,backend)
            result=finish_bsp(console,extra_members=recovered)
            pak=XboxZip(bsp_lump(result,40))
            self.assertEqual(pak.read('materials/maps/m/cubemapdefault.hdr.360.vtf'),hdr)
            self.assertIn('materials/maps/m/cubemapdefault.360.vtf',pak.entries)
            self.assertEqual(bsp_lump(result,0),bsp_lump(console,0))
            self.assertTrue(records[0]['cubemap'])
            self.assertFalse(list(backend.game.rglob('*.vtf')))

    def test_failed_conversion_and_lost_cubemap_are_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=bsp({'materials/cube.vtf':pc_texture()});console=bsp({},True)
            backend=SimpleNamespace(game=Path(tmp),run=lambda n,e:{})
            with self.assertRaisesRegex(ValueError,'individual conversion failed'):recover_embedded_textures(source,console,backend)
            backend.run=lambda n,e:{e[0]:texture()}
            with self.assertRaisesRegex(ValueError,'cubemap/frame'):recover_embedded_textures(source,console,backend)

    def test_merge_refuses_overwriting_existing_converted_data(self):
        original=texture(flags=0x4000)
        with self.assertRaisesRegex(ValueError,'Conflicting recovered'):
            finish_bsp(bsp({'materials/cube.360.vtf':original},True),extra_members={'materials/cube.360.vtf':texture()})
