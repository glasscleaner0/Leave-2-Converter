import tempfile,unittest,struct
from pathlib import Path
from unittest.mock import Mock,patch
from l4d2_converter.compatibility import recover_internal_material_aliases,supplement_missing_textures,retain_source_gaps,supplement_missing_materials


class ResourceRepairs(unittest.TestCase):
    def test_alias_uses_internal_directory_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);refs=Mock();refs.pc_read.return_value=None
            model=root/'models/deep/bus.mdl';model.parent.mkdir(parents=True);d=bytearray(100);d[12:76]=b'left4dead/vehicles/bus.mdl'.ljust(64,b'\0');model.write_bytes(d)
            source=root/'materials/models/left4dead/vehicles/body.vmt';source.parent.mkdir(parents=True);source.write_bytes(b'VertexLitGeneric { "$basetexture" "bus" }')
            missing=[{'path':'materials/models/wrong/body.vmt','owner':'models/deep/bus.mdl'}]
            with patch('l4d2_converter.compatibility.model_info',return_value={}):
                rows=recover_internal_material_aliases(root,refs,missing)
                self.assertEqual(len(rows),1);self.assertEqual((root/missing[0]['path']).read_bytes(),source.read_bytes())
                self.assertEqual(recover_internal_material_aliases(root,refs,missing),[])
                self.assertEqual(recover_internal_material_aliases(root,refs,[{'path':'materials/models/other.vmt','owner':'maps/m.bsp'}]),[])

    def test_missing_texture_shader_roles_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);refs=Mock();refs.xbox={};refs.supplemental_index={}
            refs.pc_read.side_effect=lambda n:b'normal-data' if n=='materials/dev/flat_normal.vtf' else None
            paths=['materials/models/a.vmt','materials/models/b.vmt','materials/models/unknown.vmt']
            texts=[b'VertexLitGeneric { "$basetexture" "white" "$envmapmask" "white" }',b'VertexLitGeneric { "$bumpmap" "models/missing" }',b'Water { "$basetexture" "other" }']
            for n,d in zip(paths,texts):p=root/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(d)
            missing=[{'path':'materials/white.vtf','owner':paths[0]}, {'path':'materials/models/missing.vtf','owner':paths[1]}, {'path':'materials/other.vtf','owner':paths[2]}]
            rows=supplement_missing_textures(root,refs,missing)
            self.assertEqual(len(rows),2);white=(root/'materials/white.vtf').read_bytes()
            self.assertEqual(white[:4],b'VTF\0');self.assertEqual(white[80:],bytes([255]*4))
            self.assertEqual(struct.unpack_from('<2H',white,16),(1,1))
            self.assertEqual((root/'materials/models/missing.vtf').read_bytes(),b'normal-data')
            self.assertFalse((root/'materials/other.vtf').exists())
            self.assertEqual(supplement_missing_textures(root,refs,missing),[])

    def test_only_original_missing_animation_includes_may_be_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);owner='models/a.mdl';p=root/owner;p.parent.mkdir();p.write_bytes(b'model')
            rows=[{'owner':owner,'path':'models/missing_anim.mdl'},{'owner':owner,'path':'models/a.vvd'},{'owner':'maps/m.bsp','path':'models/missing_anim.mdl'}]
            with patch('l4d2_converter.compatibility.model_info',return_value={'includes':['models/missing_anim.mdl']}):
                required,gaps=retain_source_gaps(root,{owner},rows)
                self.assertEqual(len(required),2);self.assertEqual(len(gaps),1)
                required,gaps=retain_source_gaps(root,set(),rows);self.assertEqual(required,rows);self.assertEqual(gaps,[])

    def test_non_models_material_directory_still_requires_model_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);refs=Mock();refs.xbox={'materials/dev/graygrid.vtf':True};refs.supplemental_index={};refs.pc_read.return_value=None
            rows=supplement_missing_materials(root,refs,[{'path':'materials/forest/grass.vmt','owner':'models/grass.mdl'},{'path':'materials/tools/special.vmt','owner':'maps/map.bsp'}])
            self.assertEqual(len(rows),1);self.assertFalse((root/'materials/tools/special.vmt').exists())

if __name__=='__main__':unittest.main()
