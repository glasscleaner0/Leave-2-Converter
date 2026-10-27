import struct
import tempfile
import unittest
from pathlib import Path
from test_addons import refs
from l4d2_converter.models import used_material_indices
from l4d2_converter.dependencies import discover


def model(second_body=False,eye=False):
    d=bytearray(512)
    def alloc(size):
        start=len(d);d.extend(b'\0'*size);return start
    def put(offset,*values):struct.pack_into('<'+'I'*len(values),d,offset,*values)
    d[:4]=b'IDST';put(4,49,1234)
    textures=alloc(192);put(204,3,textures,0,0)
    body=alloc(16);put(232,1,body)
    models=alloc(148*(2 if second_body else 1));put(body,0,2 if second_body else 1,0,models-body)
    for index in range(2 if second_body else 1):
        m=models+index*148;mesh=alloc(116);put(m+72,1,mesh-m,3);put(mesh,2 if index else 0)
        if eye and not index:
            eyes=alloc(172);put(m+100,1,eyes-m);put(eyes+52,2)
    skins=alloc(12);put(220,3,2,skins)
    struct.pack_into('<6H',d,skins,0,1,2,1,1,2)
    for index,name in enumerate((b'body',b'body_it',b'unused')):
        start=alloc(len(name)+1);d[start:start+len(name)]=name;put(textures+index*64,start-(textures+index*64))
    put(76,len(d));return bytes(d)


class ModelMaterials(unittest.TestCase):
    def test_all_skins_bodygroups_and_eye_materials(self):
        self.assertEqual(used_material_indices(model()),{0,1})
        self.assertEqual(used_material_indices(model(second_body=True)),{0,1,2})
        self.assertEqual(used_material_indices(model(eye=True)),{0,1,2})

    def test_unused_slots_and_orphan_vmt_do_not_block_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'models').mkdir();(root/'materials').mkdir()
            (root/'models/test.mdl').write_bytes(model())
            (root/'materials/models').mkdir()
            (root/'materials/models/orphan.vmt').write_bytes(b'Shader { "$basetexture" "absent" }')
            result=discover(root,refs(pc={'models/test.vvd':b'vvd','models/test.dx90.vtx':b'\0'*36},
                xbox={'materials/body.vmt':None,'materials/body_it.vmt':None}))
            self.assertFalse(result['missing']);self.assertFalse(result['invalid'])
            self.assertEqual(result['unused_materials'],['materials/models/orphan.vmt'])
            self.assertEqual(result['unused_model_materials'][0]['path'],'materials/unused.vmt')
            self.assertTrue((root/'materials/models/orphan.vmt').exists())

    def test_used_skin_texture_remains_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'models').mkdir();(root/'materials').mkdir()
            (root/'models/test.mdl').write_bytes(model())
            (root/'materials/body_it.vmt').write_bytes(b'Shader { "$basetexture" "absent" }')
            result=discover(root,refs(pc={'models/test.vvd':b'vvd','models/test.dx90.vtx':b'\0'*36},
                xbox={'materials/body.vmt':None}))
            self.assertEqual(result['missing'],[{'path':'materials/absent.vtf','owner':'materials/body_it.vmt'}])

    def test_lod_replacement_and_scripts_remain_required(self):
        for scripts in (False,True):
            with self.subTest(scripts=scripts),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);(root/'models').mkdir();(root/'materials').mkdir()
                (root/'models/test.mdl').write_bytes(model())
                vtx=bytearray(50);struct.pack_into('<2I',vtx,20,1,36)
                struct.pack_into('<Ii',vtx,36,1,8);struct.pack_into('<Hi',vtx,44,0,6);vtx+=b'lod_mat\0'
                if scripts:
                    (root/'scripts').mkdir();(root/'scripts/test.nut').write_bytes(b'// dynamic')
                    (root/'materials/orphan.vmt').write_bytes(b'Shader { "$basetexture" "absent" }')
                result=discover(root,refs(pc={'models/test.vvd':b'vvd','models/test.dx90.vtx':bytes(vtx)},
                    xbox={'materials/body.vmt':None,'materials/body_it.vmt':None,'materials/unused.vmt':None}))
                missing={x['path'] for x in result['missing']}
                self.assertIn('materials/lod_mat.vmt',missing)
                self.assertEqual('materials/absent.vtf' in missing,scripts)

    def test_lod_replacement_uses_cdmaterial_search_directories(self):
        for replacement in (b'lod_mat',b'models/alternate/lod_mat'):
            with self.subTest(replacement=replacement),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);(root/'models').mkdir()
                d=bytearray(model());directory=len(d)+4
                struct.pack_into('<2I',d,212,1,len(d))
                d+=struct.pack('<I',directory)+b'models/alternate/\0'
                struct.pack_into('<I',d,76,len(d))
                (root/'models/test.mdl').write_bytes(d)
                vtx=bytearray(50);struct.pack_into('<2I',vtx,20,1,36)
                struct.pack_into('<Ii',vtx,36,1,8);struct.pack_into('<Hi',vtx,44,0,6)
                vtx+=replacement+b'\0'
                native={'materials/models/alternate/'+n+'.vmt':None for n in ('body','body_it','lod_mat')}
                result=discover(root,refs(pc={'models/test.vvd':b'vvd','models/test.dx90.vtx':bytes(vtx)},xbox=native))
                self.assertFalse(result['missing']);self.assertFalse(result['invalid'])
                self.assertIn('materials/models/alternate/lod_mat.vmt',result['reference_edges']['models/test.mdl'])

    def test_bad_skin_indices_refused(self):
        d=bytearray(model());start=struct.unpack_from('<I',d,228)[0];struct.pack_into('<H',d,start,9)
        with self.assertRaisesRegex(ValueError,'outside model texture table'):used_material_indices(d)

    def test_stock_material_override_is_required_even_with_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'models').mkdir();(root/'materials').mkdir()
            (root/'models/test.mdl').write_bytes(model())
            (root/'materials/flashlight.vmt').write_bytes(b'Shader { "$basetexture" "needed" }')
            result=discover(root,refs(pc={'models/test.vvd':b'vvd','models/test.dx90.vtx':b'\0'*36},
                xbox={'materials/body.vmt':None,'materials/body_it.vmt':None,'materials/flashlight.vmt':None}))
            self.assertIn({'path':'materials/needed.vtf','owner':'materials/flashlight.vmt'},result['missing'])

    def test_custom_ui_material_is_required_even_with_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'models').mkdir();(root/'materials/vgui').mkdir(parents=True)
            (root/'models/test.mdl').write_bytes(model())
            (root/'materials/vgui/new_panel.vmt').write_bytes(b'Shader { "$basetexture" "needed" }')
            result=discover(root,refs(pc={'models/test.vvd':b'vvd','models/test.dx90.vtx':b'\0'*36},
                xbox={'materials/body.vmt':None,'materials/body_it.vmt':None}))
            self.assertIn({'path':'materials/needed.vtf','owner':'materials/vgui/new_panel.vmt'},result['missing'])


if __name__=='__main__':unittest.main()
