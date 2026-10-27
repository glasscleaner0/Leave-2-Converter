import json
from pathlib import Path
import tempfile
import unittest
from l4d2_converter.inputs import extract_inputs
from l4d2_converter.keyvalues import prepare_mission,leaf_pairs,parse,decode_text,mission_maps,tokens
from l4d2_converter.formats import color_correction,validate_asset
from l4d2_converter.dependencies import reference_name


class Missions(unittest.TestCase):
    def test_utf8_bom_and_non_latin_text_survive(self):
        source='\ufeff"mission" { "Name" "Test" "DisplayTitle" "测试战役" "modes" { "coop" { "1" { "Map" "test01" } } } }'.encode('utf8')
        name,data=prepare_mission(source)
        self.assertEqual(name,'Test')
        self.assertIn(('displaytitle','测试战役'),leaf_pairs(data))
        self.assertIn(('map','test01'),leaf_pairs(data))

    def test_comment_braces_inline_fields_and_nested_fields(self):
        source=b'// { this brace is in a comment\n"mission" { "Name" "Test" "BuiltIn" "1" "Version" "2" "modes" { "coop" { "BuiltIn" "9" "1" { "Map" "test01" } } } }'
        _,data=prepare_mission(source)
        self.assertIn(b'// { this brace is in a comment',data)
        fields=parse(decode_text(data))[0].value
        self.assertEqual([(e.key.value,e.value.value) for e in fields if not isinstance(e.value,list)],
                         [('BuiltIn','0'),('x360ctx','16'),('dlcmask','0x0000000000000000'),('Name','Test'),('Version','2')])
        self.assertIn(('builtin','9'),leaf_pairs(data))

    def test_legacy_text_bytes_preserved(self):
        source=b'"mission" { "Name" "Test" "Description" "caf\xe9\x81" }'
        _,out=prepare_mission(source)
        self.assertIn(b'caf\xe9\x81',out)

    def test_conditions_comments_and_quote_escapes(self):
        self.assertEqual(leaf_pairs(b'"Shader" { /* note */ "$baseTexture" "folder/wall" [!$X360] "note" "https://example.test" }'),
                         [('$basetexture','folder/wall'),('note','https://example.test')])
        self.assertEqual(tokens('"say \\"hello\\""',escape_sequences=True)[0].value,'say "hello"')
        self.assertEqual(leaf_pairs(b'"Shader" { "directory" "models\\" }'),[('directory','models\\')])

    def test_malformed_and_duplicate_mission_id_are_refused(self):
        for data in (b'"mission" { "Name" "T"',b'"mission" { "Name" "A" "Name" "B" }',b'"mission" { "Name" "../bad" }'):
            with self.subTest(data=data),self.assertRaises(ValueError):prepare_mission(data)

    def test_map_dependencies_only_come_from_modes(self):
        self.assertEqual(mission_maps(b'"mission" { "Name" "A" "Map" "unrelated" "modes" { "coop" { "1" { "Map" "m1" } "2" { "Map" "m2" } } "versus" { "1" { "Map" "m1" } } } }'),['m1','m2'])
        with self.assertRaises(ValueError):mission_maps(b'"mission" { "modes" { "coop" { "Map" "../m1" } } }')
        self.assertEqual(mission_maps(b'"mission" { "modes" { "coop" { "Map" "tumtara_sound+ragdoll+water" } } }'),['tumtara_sound+ragdoll+water'])
        self.assertEqual(mission_maps(b'"mission" { "modes" { "coop" { "Map" "tumtara_sky_docks_&_highrise" } } }'),['tumtara_sky_docks_&_highrise'])
        for name in ('/m1', 'a//b', 'a/./b', 'a/../b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                mission_maps(('"mission" { "modes" { "coop" { "Map" "'+name+'" } } }').encode())

    def test_rgb_lookup_preserves_palette_and_rejects_wrong_sizes(self):
        data=bytes(range(256))*384
        self.assertEqual(color_correction(data),data)
        self.assertEqual(validate_asset('materials/correction/test.360.raw',data),data)
        with self.assertRaises(ValueError):color_correction(data[:-1])

    def test_model_relative_material_reference_stays_inside_game(self):
        self.assertEqual(reference_name('materials/models/../chernobyl/models/wall.vmt','materials'),
                         'materials/chernobyl/models/wall.vmt')
        self.assertEqual(reference_name('materials/../../left4dead2/materials/models/wall.vmt','materials'),
                         'materials/models/wall.vmt')
        for name in ('materials/../../escape.vmt','C:/escape.vmt','/outside.vmt','materials/../models/wrong.vmt'):
            with self.subTest(name=name),self.assertRaises(ValueError):reference_name(name,'materials')


class Inputs(unittest.TestCase):
    def test_multipart_identical_shared_files_and_metadata_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=root/'a';b=root/'b';out=root/'out'
            for p in (a,b):p.mkdir();(p/'shared.txt').write_bytes(b'same')
            (a/'addoninfo.txt').write_bytes(b'part 1');(b/'addoninfo.txt').write_bytes(b'part 2')
            (a/'first.txt').write_bytes(b'one');(b/'second.txt').write_bytes(b'two')
            rows=extract_inputs([a,b],out)
            self.assertEqual({r['path'] for r in rows},{'shared.txt','addoninfo.txt','first.txt','second.txt'})
            shared=next(r for r in rows if r['path']=='shared.txt')
            self.assertEqual(len(shared['sources']),2)
            self.assertEqual(len(next(r for r in rows if r['path']=='addoninfo.txt')['metadata_variants']),1)
            self.assertEqual((out/'second.txt').read_bytes(),b'two')

    def test_conflicting_asset_is_never_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=root/'a';b=root/'b'
            for p,data in ((a,b'original'),(b,b'changed')):p.mkdir();(p/'model.txt').write_bytes(data)
            with self.assertRaisesRegex(ValueError,'Conflicting multipart'):
                extract_inputs([a,b],root/'out')
            self.assertEqual((root/'out/model.txt').read_bytes(),b'original')

    def test_input_limit_is_checked_before_reading_large_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'src';src.mkdir();(src/'big.txt').write_bytes(b'123456')
            with self.assertRaisesRegex(ValueError,'limit'):extract_inputs([src],root/'out',max_bytes=5)
            self.assertFalse((root/'out/big.txt').exists())

    def test_duplicate_sources_and_converted_inputs_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'src';src.mkdir();(src/'a.txt').write_bytes(b'a')
            with self.assertRaisesRegex(ValueError,'Duplicate input'):extract_inputs([src,src],root/'out')
            (src/'a.360.vtf').write_bytes(b'VTFX')
            with self.assertRaisesRegex(ValueError,'PC assets'):extract_inputs([src],root/'other')


if __name__=='__main__':unittest.main()
