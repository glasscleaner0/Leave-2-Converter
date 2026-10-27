import unittest
from l4d2_converter.material_aliases import alias_material_tree
from l4d2_converter.keyvalues import parse
class MaterialAliasTests(unittest.TestCase):
    def test_patch_chain_textures_and_conditions_preserved(self):
        files={'materials/root.vmt':b'Patch { include "materials/base.vmt" insert { "$basetexture" "body" "$wounded" "1" } }', 'materials/base.vmt':b'Infected { "$gradienttexture" "palette" "$burndetailtexture" "burn" "$woundcutouttexture" "cutout" "$envmap" "env_cubemap" Proxies { Infected { resultVar "$color" } } }'}
        for n in ['body','palette','burn','cutout']:files['materials/'+n+'.vtf']=n.encode()
        out,record=alias_material_tree(['materials/root.vmt'],files.get,'leave2test/infected')
        self.assertEqual(record['textures'],4);self.assertEqual(record['included_materials'],1)
        self.assertEqual(parse(out['materials/root.vmt'].decode())[0].key.value,'Patch')
        base=out[next(iter(record['include_aliases'].values()))]
        self.assertIn(b'Infected',base);self.assertIn(b'Proxies',base);self.assertIn(b'"env_cubemap"',base);self.assertIn(b'"$color"',base)
        for old,new in record['texture_aliases'].items():self.assertEqual(out[new],files[old])
        self.assertEqual(alias_material_tree(['materials/root.vmt'],files.get,'leave2test/infected'),(out,record))
    def test_include_cycle_rejected(self):
        files={'materials/a.vmt':b'Patch { include "b" }','materials/b.vmt':b'Patch { include "a" }'}
        with self.assertRaisesRegex(ValueError,'cycle'):alias_material_tree(['materials/a.vmt'],files.get,'test')
    def test_missing_texture_is_explicit(self):
        with self.assertRaisesRegex(ValueError,'Missing PC texture'):alias_material_tree(['materials/a.vmt'],lambda n:b'Infected { "$basetexture" "missing" }' if n.endswith('.vmt') else None,'test')
