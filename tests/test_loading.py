import struct
import unittest
from l4d2_converter.resources import resource_lists
from l4d2_converter.textures import texture_info, texture_budget
from l4d2_converter.archive import aligned_zip


def texture(width=512, height=512, frames=1, flags=0, image_format=15):
    data = bytearray(68)
    data[:4] = b'VTFX'
    struct.pack_into('>4I', data, 4, 0x360, 8, 68, flags)
    struct.pack_into('>5H', data, 20, width, height, 1, frames, 68)
    data[31] = 1
    struct.pack_into('>I', data, 48, image_format)
    data[60:64] = b'\x30\0\0\0'
    struct.pack_into('>I', data, 64, 68)
    data.extend(b'\0' * 16)
    return bytes(data)


class Loading(unittest.TestCase):
    def test_budget_includes_embedded_textures_with_per_map_ownership(self):
        tex=texture(width=128,height=128)
        pak=aligned_zip({'materials/embedded.360.vtf':tex})
        bsp=bytearray(1036);bsp[:8]=b'PSBV'+struct.pack('>I',20)
        struct.pack_into('>4I',bsp,8+40*16,1036,len(pak),0,0);bsp.extend(pak)
        report,_=texture_budget({'materials/loose.360.vtf':tex},maps={'maps/test.360.bsp':bytes(bsp)})
        size=texture_info(tex)['logical_image_bytes']
        self.assertEqual(report['logical_image_bytes'],2*size)
        self.assertEqual(report['archive_logical_image_bytes'],size)
        self.assertEqual(report['maps'][0]['embedded_logical_image_bytes'],size)
        self.assertEqual({r['container'] for r in report['textures']},{'addon-archive','maps/test.360.bsp'})

    def test_animated_texture_budget_counts_all_frames(self):
        # Observed doors addon is 58 frames of 512x512 DXT5, not one image.
        info = texture_info(texture(frames=58))
        self.assertEqual(info['frames'], 58)
        self.assertEqual(info['image_format'], 15)
        self.assertEqual(info['logical_image_bytes'], 20274016)
        stock = texture()
        report, warnings = texture_budget({'materials/door.360.vtf':texture(frames=58)}, lambda _:stock)
        self.assertEqual(report['textures'][0]['logical_growth_bytes'], 57*349552)
        self.assertTrue(any('58 frames' in x for x in warnings))

    def test_nommip_and_cubemap_size(self):
        self.assertEqual(texture_info(texture(flags=0x100))['logical_image_bytes'], 512*512)
        self.assertEqual(texture_info(texture(flags=0x4100))['logical_image_bytes'], 6*512*512)

    def test_bad_resource_offsets_and_zero_frames_are_rejected(self):
        data = bytearray(texture())
        struct.pack_into('>I', data, 64, 999)
        with self.assertRaises(ValueError):texture_info(data)
        data = bytearray(texture());struct.pack_into('>H', data, 26, 0)
        with self.assertRaises(ValueError):texture_info(data)

    def test_unknown_format_does_not_claim_zero_memory_use(self):
        report, warnings = texture_budget({'materials/new.360.vtf':texture(image_format=999)})
        self.assertIsNone(report['textures'][0]['logical_image_bytes'])
        self.assertEqual(report['unknown_formats'], 1)
        self.assertTrue(any('incomplete' in s for s in warnings))

    def test_default_loading_does_not_prefetch_foreign_map(self):
        members = {'models/example.360.mdl':b'x', 'materials/maps/c1m1_hotel/wall.vmt':b'x'}
        self.assertEqual(resource_lists({'maps/new.360.bsp':b'x'}, members), {})

    def test_optional_lists_exclude_other_maps_and_loader_companions(self):
        members = {'materials/own.360.vtf':b'x', 'models/own.360.mdl':b'x',
                   'models/own.dx90.360.vtx':b'x', 'models/own.360.vvd':b'x',
                   'maps/other.360.nav':b'x', 'scripts/a.nut':b'x',
                   'missions/a.txt':b'x', 'stringtable_dictionary_fallback_xbox.dct':b'x'}
        output = resource_lists({'maps/new.360.bsp':b'x'}, members, 'addon-local')
        self.assertEqual(output['reslists_xbox/new.360.lst'],
            b'"maps\\new.bsp"\n"materials\\own.vtf"\n"models\\own.mdl"\n')
        with self.assertRaises(ValueError):resource_lists({}, {}, 'hotel')


if __name__ == '__main__':unittest.main()
