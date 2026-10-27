import tempfile,unittest
from pathlib import Path
from l4d2_converter.dependencies import discover

class References:
    xbox={'materials/glass/base.vmt':True}
    supplemental_index={}
    pc={}
    def pc_read(self,name):
        return {'materials/glass/base.vmt':b'LightmappedGeneric { "$basetexture" "glass/pane" "$translucent" "1" }',
                'materials/glass/pane.vtf':b'actual-texture'}.get(name)

class PortablePatch(unittest.TestCase):
    def test_input_material_keeps_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'materials/glass/base.vmt';p.parent.mkdir(parents=True)
            own=b'UnlitGeneric { "$color" "[1 0 0]" }';p.write_bytes(own)
            result=discover(root,References(),include_duplicate_textures=True)
            self.assertFalse(result['missing']);self.assertEqual(p.read_bytes(),own)

    def test_compatibility_stages_base_and_texture_instead_of_native_shortcut(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'materials/pane.vmt';p.parent.mkdir()
            p.write_bytes(b'Patch { include "materials/GLASS/base.vmt" replace { "$envmap" "env_cubemap" } }')
            plain=discover(root,References())
            self.assertFalse((root/'materials/glass/base.vmt').exists())
            self.assertIn('materials/glass/base.vmt',plain['native_reused'])
            fixed=discover(root,References(),include_duplicate_textures=True)
            self.assertFalse(fixed['missing']);self.assertFalse(fixed['invalid'])
            self.assertEqual((root/'materials/glass/pane.vtf').read_bytes(),b'actual-texture')
            self.assertIn(b'$translucent',(root/'materials/glass/base.vmt').read_bytes())
            self.assertIn('materials/glass/base.vmt',[row['path'] for row in fixed['added']])
            self.assertEqual(p.read_bytes(),b'Patch { include "materials/GLASS/base.vmt" replace { "$envmap" "env_cubemap" } }')

if __name__=='__main__':unittest.main()
