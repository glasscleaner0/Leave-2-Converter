import struct
import unittest
from l4d2_converter.vtx import relayout,prepare_source,finish_console,layout
from l4d2_converter.formats import pack_source,unpack_source

def fixture(endian='<'):
    data=bytearray(156)
    for offset,value in ((0,7),(4,24),(12,3),(16,123),(20,1),(24,148),(28,1),(32,36),
                         (36,1),(40,8),(44,1),(48,8),(52,1),(56,12),(64,1),(68,9),
                         (73,1),(77,52),(81,3),(85,61),(89,1),(93,25),
                         (98,3),(102,0),(106,1),(110,0),(117,1),(121,42)):
        struct.pack_into(endian+'I',data,offset,value)
    data[97]=2;struct.pack_into(endian+'H',data,114,1);data[116]=1
    data[125:134]=bytes(range(9));data[134:140]=bytes(range(6));data[140:148]=bytes(range(8))
    return bytes(data)

class Vtx(unittest.TestCase):
    def test_sdk_roundtrip_preserves_entire_legacy_file(self):
        source=fixture();new,record=prepare_source(source)
        self.assertEqual(len(new),len(source)+16)
        self.assertTrue(record['geometry_and_bone_buffers_exact'])
        self.assertEqual(layout(new,'<',33,35)[3]['strips'],1)
        old,record=relayout(new,'<',(33,35),(25,27))
        self.assertEqual(old,source)

    def test_console_compression_and_native_layout_preserved(self):
        native=fixture('>');modern,_=relayout(native,'>',(25,27),(33,35))
        output,record=finish_console(modern[:36]+pack_source(modern[36:]))
        self.assertEqual(output[:36]+unpack_source(output[36:]),native)
        self.assertTrue(record['geometry_and_bone_buffers_exact'])

    def test_nonzero_topology_is_not_discarded(self):
        modern,_=relayout(fixture(),'<',(25,27),(33,35));bad=bytearray(modern)
        struct.pack_into('<I',bad,73+25,1);struct.pack_into('<I',bad,73+29,68)
        self.assertEqual(prepare_source(bytes(bad))[0],bytes(bad))
        with self.assertRaisesRegex(ValueError,'topology'):relayout(bad,'<',(33,35),(25,27))

    def test_empty_bone_change_table_ignores_unused_offset(self):
        data=bytearray(fixture());struct.pack_into('<I',data,117,0)
        struct.pack_into('<i',data,121,0x7fffffff)
        adapted,record=prepare_source(bytes(data))
        restored,_=relayout(adapted,'<',(33,35),(25,27))
        self.assertEqual(restored,bytes(data))
        struct.pack_into('<I',data,117,1)
        with self.assertRaises(ValueError):prepare_source(bytes(data))

    def test_invalid_geometry_ranges_are_rejected(self):
        bad=bytearray(fixture());struct.pack_into('<I',bad,98,1000)
        with self.assertRaises(ValueError):prepare_source(bad)
        with self.assertRaises(ValueError):prepare_source(b'bad')

if __name__=='__main__':unittest.main()
