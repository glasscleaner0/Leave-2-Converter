import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from l4d2_converter.core import addon_kind
from l4d2_converter.dependencies import discover, canonical
from l4d2_converter.models import model_info, validate_bundle,repair_length_metadata
from l4d2_converter.archive import aligned_zip


def mdl(mesh=False, endian='<'):
    data = bytearray(676 if mesh else 512)
    data[:4] = b'IDST' if endian == '<' else b'TSDI'
    struct.pack_into(endian + '2I', data, 4, 49, 1234)
    struct.pack_into(endian + 'I', data, 76, len(data))
    if mesh:
        struct.pack_into(endian + '2I', data, 232, 1, 512)
        struct.pack_into(endian + '4I', data, 512, 0, 1, 0, 16)
        struct.pack_into(endian + '3I', data, 528 + 72, 1, 0, 3)
    return bytes(data)


def refs(pc=None, xbox=None, supplemental=None):
    pc = pc or {}; supplemental = supplemental or {}
    return SimpleNamespace(pc=pc, xbox=xbox or {}, supplemental=supplemental,
        supplemental_index={canonical(n):n for n in supplemental}, pc_read=pc.get)


class Addons(unittest.TestCase):
    def test_invalid_material_reference_does_not_abort_other_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'materials').mkdir()
            (root/'materials/bad.vmt').write_bytes(b'"Shader" { "$basetexture" "../escape" }')
            (root/'materials/good.vmt').write_bytes(b'"Shader" { "$basetexture" "needed" }')
            result=discover(root,refs())
            self.assertEqual(result['invalid'][0]['path'],'materials/bad.vmt')
            self.assertEqual(result['missing'][0]['path'],'materials/needed.vtf')

    def test_nonpath_entity_text_does_not_abort_dependency_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'maps').mkdir()
            bsp=bytearray(1040);bsp[:8]=b'VBSP'+struct.pack('<I',20)
            for lump,data in ((0,b'{ "message" "legacy\\x8d text" }'.replace(b'\\x8d',b'\x8d')),(35,b'\0'*4),(40,aligned_zip({}))):
                struct.pack_into('<4I',bsp,8+lump*16,len(bsp),len(data),0,0);bsp+=data
            (root/'maps/test.bsp').write_bytes(bsp)
            self.assertFalse(discover(root,refs())['missing'])

    def test_opt_in_stale_model_length_repair_only_changes_length_field(self):
        original=bytearray(mdl());struct.pack_into('<I',original,76,len(original)+12)
        fixed,details=repair_length_metadata('models/test.mdl',{'models/test.mdl':bytes(original)})
        self.assertEqual(bytes(original[:76]+original[80:]),fixed[:76]+fixed[80:])
        self.assertEqual(model_info(fixed)['checksum'],1234)
        self.assertTrue(details['payload_bytes_unchanged'])
        bad=bytearray(original);struct.pack_into('<I',bad,76,200000)
        with self.assertRaisesRegex(ValueError,'too large'):
            repair_length_metadata('models/test.mdl',{'models/test.mdl':bytes(bad)})

    def test_length_repair_refuses_truncated_model_material_table(self):
        original=bytearray(mdl());struct.pack_into('<I',original,76,len(original)+12)
        struct.pack_into('<4I',original,204,1,500,0,0)
        with self.assertRaisesRegex(ValueError,'truncated'):
            repair_length_metadata('models/test.mdl',{'models/test.mdl':bytes(original)})

    def test_invalid_model_does_not_abort_remaining_dependency_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'models').mkdir();(root/'materials').mkdir()
            (root/'models/bad.mdl').write_bytes(b'bad')
            (root/'materials/test.vmt').write_bytes(b'"Shader" { "$basetexture" "missing" }')
            result=discover(root,refs())
            self.assertEqual(result['invalid'][0]['path'],'models/bad.mdl')
            self.assertEqual(result['missing'][0]['path'],'materials/missing.vtf')

    def test_type_does_not_require_campaign_for_replacement(self):
        self.assertEqual(addon_kind(['materials/models/katana.vmt']), 'resource-addon')
        self.assertEqual(addon_kind(['maps/test.bsp']), 'campaign')
        self.assertEqual(addon_kind(['missions/incomplete.txt']), 'campaign')

    def test_replacement_material_missing_dependency_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'materials/test.vmt';p.parent.mkdir();p.write_bytes(b'"Shader" { "$basetexture" "missing" }')
            r = discover(tmp, refs())
            self.assertEqual(r['missing'], [{'path':'materials/missing.vtf','owner':'materials/test.vmt'}])

    def test_only_referenced_console_supplement_is_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'materials/test.vmt';p.parent.mkdir();p.write_bytes(b'"Shader" { "$basetexture" "needed" }')
            r = discover(tmp, refs(supplemental={'materials/needed.360.vtf':b'VTFX', 'materials/unrelated.360.vtf':b'VTFX'}))
            self.assertEqual(r['supplemental_used'], ['materials/needed.360.vtf'])
            self.assertFalse(r['missing'])

    def test_native_companions_do_not_satisfy_pc_model_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'models/test.mdl';p.parent.mkdir();p.write_bytes(mdl(mesh=True))
            r = discover(tmp, refs(xbox={'models/test.vvd':None,'models/test.dx90.vtx':None}))
            self.assertEqual({m['path'] for m in r['missing']}, {'models/test.vvd','models/test.dx90.vtx'})

    def test_companion_checksum_mismatch_rejected_in_both_endiannesses(self):
        for endian, console in (('<',False),('>',True)):
            with self.subTest(console=console):
                suffix = '.360' if console else ''
                name = 'models/test'+suffix+'.mdl'
                vvd = bytearray(16);vvd[:4] = b'VSDI' if console else b'IDSV'
                struct.pack_into(endian+'I', vvd, 8, 1234)
                vtx = bytearray(20);struct.pack_into(endian+'I', vtx, 16, 1234)
                members={name:mdl(mesh=True,endian=endian),'models/test'+suffix+'.vvd':vvd,
                    'models/test.dx90'+suffix+'.vtx':vtx}
                self.assertEqual(validate_bundle(name,members,console)['vertices'],3)
                struct.pack_into(endian+'I', vtx,16,9999)
                with self.assertRaisesRegex(ValueError,'checksum mismatch'):
                    validate_bundle(name,members,console)

    def test_animation_only_model_does_not_require_geometry(self):
        self.assertEqual(validate_bundle('models/test.mdl',{'models/test.mdl':mdl()})['meshes'],0)

    def test_unused_campaign_material_does_not_add_a_missing_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'materials').mkdir();(root/'maps').mkdir()
            (root/'materials/unused.vmt').write_bytes(b'"Shader" { "$basetexture" "missing" }')
            pak = aligned_zip({})
            bsp = bytearray(1040)
            bsp[:8] = b'VBSP' + struct.pack('<I',20)
            struct.pack_into('<4I',bsp,8+35*16,1036,4,0,0)
            struct.pack_into('<4I',bsp,8+40*16,1040,len(pak),0,0)
            bsp.extend(pak)
            (root/'maps/test.bsp').write_bytes(bsp)
            self.assertFalse(discover(root,refs())['missing'])


if __name__ == '__main__':
    unittest.main()
