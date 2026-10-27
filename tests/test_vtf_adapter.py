import struct
import unittest
from l4d2_converter.vtf_adapter import expand_intensity

class Intensity(unittest.TestCase):
    def source(self,fmt=5,resource=False):
        header=104 if resource else 80
        d=bytearray(header);d[:4]=b'VTF\0'
        struct.pack_into('<3I',d,4,7,4 if resource else 2,header)
        struct.pack_into('<2H',d,16,2,2);struct.pack_into('<H',d,24,1)
        struct.pack_into('<I',d,52,fmt);d[56]=2
        struct.pack_into('<I',d,57,0xffffffff);struct.pack_into('<H',d,63,1)
        raw=bytes([10,20,30,40,50]) if fmt==5 else bytes([10,1,20,2,30,3,40,4,50,5])
        if resource:
            struct.pack_into('<I',d,68,3)
            d[80:84]=b'\x30\0\0\0';struct.pack_into('<I',d,84,header)
            d[88:92]=b'KVD\0';struct.pack_into('<I',d,92,header+len(raw))
            d[96:100]=b'LOD\2';struct.pack_into('<I',d,100,123)
        return bytes(d)+raw+(b'unchanged' if resource else b'')
    def test_i8_all_mips(self):
        out,rec=expand_intensity(self.source())
        self.assertEqual(out[80:],b''.join(bytes((v,v,v,255)) for v in (10,20,30,40,50)))
        self.assertEqual(rec['mips'],2)
    def test_ia88_resources_and_alpha(self):
        out,rec=expand_intensity(self.source(6,True))
        self.assertEqual(out[104:124],b''.join(bytes((v,v,v,a)) for v,a in ((10,1),(20,2),(30,3),(40,4),(50,5))))
        self.assertEqual(struct.unpack_from('<I',out,92)[0],124)
        self.assertEqual(out[124:],b'unchanged')
        self.assertEqual(struct.unpack_from('<I',out,100)[0],123)
    def test_legacy_71_has_implicit_depth(self):
        d=bytearray(self.source());struct.pack_into('<2I',d,8,1,64)
        d=bytes(d[:64])+bytes(d[80:])
        out,record=expand_intensity(d)
        self.assertEqual(len(out),84);self.assertEqual(record['pixels'],5)

    def test_refuses_truncated_or_unsupported_semantics(self):
        with self.assertRaises(ValueError):expand_intensity(self.source()[:-1])
        d=bytearray(self.source());struct.pack_into('<I',d,20,0x4000)
        with self.assertRaises(ValueError):expand_intensity(d)
        d=bytearray(self.source());struct.pack_into('<I',d,52,13)
        self.assertIsNone(expand_intensity(d))
