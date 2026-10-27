import unittest,struct,hashlib
from l4d2_converter.vtf_adapter import legacy_ui_mips

class LegacyUI(unittest.TestCase):
    def source(self):
        h=bytearray(80);h[:4]=b'VTF\0';struct.pack_into('<3I',h,4,7,2,80)
        struct.pack_into('<2H',h,16,1024,2);struct.pack_into('<I',h,20,768)
        struct.pack_into('<H',h,24,1);struct.pack_into('<I',h,52,2);h[56]=1
        struct.pack_into('<I',h,57,0xffffffff);struct.pack_into('<H',h,63,1)
        return bytes(h)+bytes((12,24,36))*2048
    def test_top_pixels_flags_and_headers_preserved(self):
        src=self.source();out,rec=legacy_ui_mips(src)
        self.assertEqual(out[-6144:],src[80:]);self.assertEqual(out[:56],src[:56]);self.assertEqual(out[57:80],src[57:80])
        self.assertEqual(out[56],11);self.assertTrue(rec['source_top_image_preserved'])
        self.assertEqual(rec['top_image_sha256'],hashlib.sha256(src[80:]).hexdigest())
        self.assertEqual(out[80:83],bytes((12,24,36)))
    def test_rejects_truncation_and_unknown_trailing_data(self):
        for data in (self.source()[:-1],self.source()+b'unknown'):
            with self.assertRaises(ValueError):legacy_ui_mips(data)
    def test_unsupported_formats_versions_and_existing_mips_not_rewritten(self):
        for off,fmt,value in ((52,'I',13),(8,'I',4),(56,'B',2),(20,'I',0)):
            src=bytearray(self.source());struct.pack_into('<'+fmt,src,off,value)
            self.assertIsNone(legacy_ui_mips(src))
    def test_animated_or_cubemap_refused(self):
        for off,fmt,value in ((24,'H',2),(20,'I',768|0x4000)):
            src=bytearray(self.source());struct.pack_into('<'+fmt,src,off,value)
            with self.assertRaises(ValueError):legacy_ui_mips(src)
