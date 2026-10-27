import struct
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock,patch
from l4d2_converter.compatibility import (prune_mission,apply_repairs,repair_legacy_pistol_entities,replace_entity_lump,supplement_missing_materials,repair_mission_mode_braces)
from l4d2_converter.formats import bsp_lump,bsp_rows
from l4d2_converter.keyvalues import mission_maps,mission_modes
from l4d2_converter.core import Options


class Compatibility(unittest.TestCase):
    def test_default_is_strict(self):
        self.assertFalse(Options('input','sdk','output','xbox').compatibility_repairs)
        self.assertFalse(Options('input','sdk','output','xbox').force_supplemented_resources)

    def test_prune_only_missing_chapters_retains_metadata_modes_and_available_maps(self):
        src=b'// original author\n"mission" { "Name" "A" "Author" "Original" "modes" { "coop" { "1" { "Map" "absent" } } "survival" { "1" { "Map" "present" "Image" "maps/present" } "2" { "Map" "absent" } } "scavenge" { "1" { "Map" "present" } } } }'
        out,removed=prune_mission(src,lambda n:n=='present')
        self.assertEqual(mission_maps(out),['present'])
        self.assertEqual(mission_modes(out),['survival','scavenge'])
        self.assertIn(b'// original author',out);self.assertIn(b'"Author" "Original"',out)
        self.assertIn(b'"Image" "maps/present"',out);self.assertEqual(len(removed),2)
        same,removed=prune_mission(src,lambda n:True);self.assertEqual(same,src);self.assertEqual(removed,[])

    def test_ambiguous_chapter_is_not_silently_removed(self):
        src=b'"mission" { "modes" { "survival" { "1" { "Map" "present" "nested" { "Map" "absent" } } } } }'
        with self.assertRaises(ValueError):prune_mission(src,lambda n:n=='present')

    def test_standalone_model_addon_is_never_trimmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'models/zombie/fast.mdl';p.parent.mkdir(parents=True);p.write_bytes(b'original')
            self.assertEqual(apply_repairs(Path(tmp),Mock()),[]);self.assertEqual(p.read_bytes(),b'original')

    def test_scripts_npc_entities_and_explicit_references_prevent_omission(self):
        for kind in ('script','npc','reference'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);(root/'maps').mkdir();(root/'maps/m.bsp').write_bytes(b'bsp')
                p=root/'models/zombie/fast.mdl';p.parent.mkdir(parents=True);p.write_bytes(b'original')
                if kind=='script':
                    s=root/'scripts/test.nut';s.parent.mkdir();s.write_bytes(b'dynamic')
                entity=b'"classname" "npc_fastzombie"' if kind=='npc' else b'"model" "models/zombie/fast.mdl"' if kind=='reference' else b''
                refs=Mock();refs.xbox={};refs.supplemental_index={};refs.pc_read.return_value=None
                with patch('l4d2_converter.compatibility.bsp_lump',side_effect=lambda b,i:entity if i==0 else b''),patch('l4d2_converter.compatibility.static_prop_summary',return_value={'models':[]}),patch('l4d2_converter.compatibility.model_info',return_value={'includes':[]}):
                    rows=apply_repairs(root,refs)
                self.assertFalse(rows);self.assertEqual(p.read_bytes(),b'original')

    def test_real_dependency_prevents_flat_normal_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'maps').mkdir();(root/'maps/m.bsp').write_bytes(b'bsp')
            p=root/'materials/test.vmt';p.parent.mkdir();p.write_bytes(b'"$bumpmap" "RealWorldTextures/Floor/MixTile/Bump/512"')
            refs=Mock();refs.xbox={};refs.supplemental_index={}
            bump='materials/realworldtextures/floor/mixtile/bump/512.vtf'
            refs.pc_read.side_effect=lambda n:b'recovered' if n==bump else None
            with patch('l4d2_converter.compatibility.bsp_lump',return_value=b''),patch('l4d2_converter.compatibility.static_prop_summary',return_value={'models':[]}):
                rows=apply_repairs(root,refs)
            self.assertFalse(any(row['path']==bump for row in rows))
            self.assertFalse((root/bump).exists())  # Normal dependency resolver imports the actual file.


    def test_mixed_pistol_spawns_get_correct_models_and_unknown_entities_stay(self):
        old=b'models/w_models/weapons/w_pistol_1911.mdl'
        src=b'\n'.join(b'{ "classname" "'+kind+b'" "model" "'+old+b'" '+extra+b' }' for kind,extra in (
            (b'weapon_pistol_spawn',b'"hammerid" "1"'),
            (b'weapon_pistol_magnum_spawn',b''),
            (b'weapon_spawn',b'"weapon_selection" "weapon_pistol_magnum"'),
            (b'prop_dynamic',b''),(b'weapon_spawn',b'"weapon_selection" "any"')))
        out,rows=repair_legacy_pistol_entities(src,lambda n:True)
        self.assertEqual(len(rows),3)
        self.assertEqual(out.count(b'w_pistol_a.mdl'),1)
        self.assertEqual(out.count(b'w_desert_eagle.mdl'),2)
        self.assertEqual(out.count(old),2)
        self.assertEqual(rows[0]['hammerid'],'1')
        self.assertEqual(repair_legacy_pistol_entities(src,lambda n:False),(src,[]))
        self.assertEqual(repair_legacy_pistol_entities(out,lambda n:True),(out,[]))

    def test_entity_repair_preserves_other_lumps_and_original_payload(self):
        for version in (20,21):
            with self.subTest(version=version):
                src=bytearray(1049);src[:8]=b'VBSP'+struct.pack('<I',version)
                src[1036:1041]=b'{ }\x00!';src[1041:]=b'geometry'
                for index,off,size in ((0,1036,5),(3,1041,8)):
                    row=(off,size,0,0) if version==20 else (0,off,size,0)
                    struct.pack_into('<4I',src,8+16*index,*row)
                out=replace_entity_lump(src,b'{ "new" "entity" }\x00')
                self.assertEqual(bsp_lump(out,0),b'{ "new" "entity" }\x00')
                self.assertEqual(bsp_lump(out,3),b'geometry')
                self.assertEqual(bsp_rows(out)[1:],bsp_rows(src)[1:])
                self.assertEqual(out[24:len(src)],src[24:])
        with self.assertRaises(ValueError):replace_entity_lump(b'PSBV',b'')

    def test_orphan_companions_omitted_only_without_references_or_scripts(self):
        for protected in ('none','map','script','reference','malformed'):
            with self.subTest(protected=protected),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);(root/'maps').mkdir();(root/'maps/m.bsp').write_bytes(b'bsp')
                stem='models/orphan';p=root/(stem+'.phy');p.parent.mkdir();p.write_bytes(b'original')
                (root/(stem+'.vvd')).write_bytes(b'original')
                if protected=='script':
                    (root/'scripts').mkdir();(root/'scripts/dynamic.nut').write_bytes(b'test')
                if protected=='malformed':(root/'models/other.mdl').write_bytes(b'bad')
                refs=Mock();refs.xbox={};refs.supplemental_index={};refs.pc_read.side_effect=lambda n:b'real' if protected=='reference' and n==stem+'.mdl' else None
                entity=b'"model" "models/orphan.mdl"' if protected=='map' else b''
                with patch('l4d2_converter.compatibility.bsp_lump',side_effect=lambda b,i:entity if i==0 else b''),patch('l4d2_converter.compatibility.static_prop_summary',return_value={'models':[]}),patch('l4d2_converter.compatibility.model_info',side_effect=ValueError('malformed')):
                    rows=apply_repairs(root,refs)
                self.assertEqual(p.exists(),protected!='none')
                self.assertEqual(bool(rows),protected=='none')

    def test_supplementation_is_limited_reported_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);refs=Mock();refs.xbox={'materials/dev/graygrid.vtf':True};refs.supplemental_index={};refs.pc_read.return_value=None
            missing=[{'path':'materials/models/subway/missing.vmt','owner':'models/subway.mdl'},
                {'path':'materials/models/subway/missing.vmt','owner':'models/subway2.mdl'},
                {'path':'materials/tools/toolsnodraw.vmt','owner':'maps/m.bsp'},
                {'path':'models/missing.mdl','owner':'maps/m.bsp'},
                {'path':'materials/models/subway/missing.vtf','owner':'materials/model.vmt'}]
            rows=supplement_missing_materials(root,refs,missing)
            self.assertEqual(len(rows),1);self.assertEqual(len(rows[0]['owners']),2)
            p=root/rows[0]['path'];self.assertIn(b'dev/graygrid',p.read_bytes())
            p.write_bytes(b'original');self.assertEqual(supplement_missing_materials(root,refs,missing),[])
            self.assertEqual(p.read_bytes(),b'original')
            p.unlink();refs.pc_read.side_effect=lambda n:b'real' if n==rows[0]['path'] else None
            self.assertEqual(supplement_missing_materials(root,refs,missing),[])
            self.assertFalse(p.exists())



    def test_orphan_reference_parent_checksum_must_match(self):
        for checksum in (123,456):
            with self.subTest(checksum=checksum),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);(root/'maps').mkdir();(root/'maps/m.bsp').write_bytes(b'bsp')
                p=root/'models/orphan.vvd';p.parent.mkdir();p.write_bytes(b'IDSV'+struct.pack('<II',4,123))
                refs=Mock();refs.xbox={};refs.supplemental_index={};refs.pc_read.side_effect=lambda n:b'parent' if n=='models/orphan.mdl' else None
                with patch('l4d2_converter.compatibility.bsp_lump',return_value=b''),patch('l4d2_converter.compatibility.static_prop_summary',return_value={'models':[]}),patch('l4d2_converter.compatibility.model_info',return_value={'checksum':checksum}):
                    rows=apply_repairs(root,refs)
                self.assertEqual(p.exists(),checksum==123)
                self.assertEqual(bool(rows),checksum!=123)


    def test_missing_mode_brace_repaired_without_guessing_other_syntax(self):
        src=b'"mission" { "Name" "Test" "modes" { "coop" { "1" { "Map" "one" } "versus" { "1" { "Map" "two" } } } }'
        out,edits=repair_mission_mode_braces(src)
        self.assertEqual(mission_modes(out),['coop','versus'])
        self.assertEqual(mission_maps(out),['one','two'])
        self.assertEqual(len(edits),1)
        self.assertEqual(repair_mission_mode_braces(out),(out,[]))
        for bad in (b'"mission" { "Name" "Test"',b'"mission" { "modes" { "coop" { "1" { "Map" "one" } "mystery" { } } }',b'"mission" { "Name" "unterminated'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):repair_mission_mode_braces(bad)

if __name__=='__main__':unittest.main()
