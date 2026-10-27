import unittest
from l4d2_converter.models import internal_model_name
class Names(unittest.TestCase):
    def test_long_archive_path_keeps_existing_valid_name(self):
        d=bytearray(512);d[:4]=b'IDST';d[12:23]=b'vehicle.mdl'
        name='models/'+('long/'*20)+'vehicle.mdl'
        result,record=internal_model_name(name,bytes(d))
        self.assertEqual(result,b'vehicle.mdl');self.assertTrue(record['archive_path_unchanged'])
    def test_normal_names_unchanged_and_bad_fallback_rejected(self):
        self.assertEqual(internal_model_name('models/a.mdl',b'')[0],b'a.mdl')
        d=bytearray(512);d[:4]=b'IDST';d[12:76]=b'x'*64
        with self.assertRaises(ValueError):internal_model_name('models/'+('x'*70)+'.mdl',bytes(d))
