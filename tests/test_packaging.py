import unittest
from l4d2_converter.core import package_layout,Options
from l4d2_converter.archive import aligned_zip,XboxZip


class Packaging(unittest.TestCase):
    def setUp(self):
        self.maps={'maps/test.360.bsp':b'converted map bytes'}
        self.missions={'missions/test.txt':b'"mission" { "Name" "Test" }'}
        self.assets={'maps/test.360.nav':b'converted nav', 'materials/test.360.vtf':b'converted texture',**self.missions}

    def test_default_retains_existing_split_installation(self):
        for key in ('single_zip','xdreanims_compatibility','force_xdreanims_missing_gestures'):
            self.assertNotIn(key,Options.__dataclass_fields__)
            with self.assertRaises(TypeError):Options('input','sdk','output','xbox',**{key:True})
        packed,loose=package_layout(self.assets,self.maps,self.missions)
        self.assertEqual(loose,{**self.maps,**self.missions})
        archive=XboxZip(aligned_zip(packed))
        self.assertNotIn('maps/test.360.bsp',archive.entries)
        self.assertEqual(archive.read('maps/test.360.nav'),self.assets['maps/test.360.nav'])


if __name__=='__main__':unittest.main()
