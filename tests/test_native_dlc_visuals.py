from pathlib import Path
import tempfile,unittest
from unittest.mock import patch
from l4d2_converter.archive import aligned_zip
from l4d2_converter.native_dlc_visuals import collect_visual_support,startup_icon_members,startup_visual_members,MINIGUN


class NativeDlcVisuals(unittest.TestCase):
    def archive(self,folder,name,texture):
        materials={
            'materials/vgui/achievements/ach_test.vmt':b'UnlitGeneric { "$basetexture" "vgui/achievements/ach_test" }',
            'materials/vgui/achievements/ach_test.360.vtf':texture,
            MINIGUN:b'''VertexLitGeneric { "$basetexture" "models/w_models/minigun/base" "$detail" "models/w_models/minigun/glow"
                "$phong" "1" Proxies { Heat { resultVar "$heatamount" } Equals { srcVar1 "$heatamount" resultVar "$detailblendfactor" } } }''',
            'materials/models/w_models/minigun/base.360.vtf':texture+b'base',
            'materials/models/w_models/minigun/glow.360.vtf':texture+b'glow'}
        path=Path(folder)/name;path.write_bytes(aligned_zip(materials));return path

    @patch('l4d2_converter.native_dlc_visuals.validate_asset')
    def test_keeps_native_payloads_and_heat_proxy_and_uses_latest_source(self,_):
        with tempfile.TemporaryDirectory() as folder:
            first=self.archive(folder,'first.zip',b'old');last=self.archive(folder,'last.zip',b'new')
            members,report=collect_visual_support([first,last])
            self.assertEqual(report['achievement_ids'],['ach_test'])
            textures=[v for n,v in members.items() if n.endswith('.vtf')]
            self.assertEqual(set(textures),{b'new',b'newbase',b'newglow'})
            self.assertIn(b'Heat',members[MINIGUN]);self.assertIn(b'$heatamount',members[MINIGUN])
            self.assertIn(b'$phong',members[MINIGUN])
            icons=startup_icon_members(members)
            self.assertEqual(len(icons),2);self.assertNotIn(MINIGUN,icons)
            self.assertFalse(report['pc_assets_used'])

    @patch('l4d2_converter.native_dlc_visuals.validate_asset')
    def test_missing_icon_texture_stops_before_partial_support_is_returned(self,_):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'broken.zip';path.write_bytes(aligned_zip({
                'materials/vgui/achievements/ach_test.vmt':b'UnlitGeneric { "$basetexture" "vgui/achievements/missing" }'}))
            with self.assertRaisesRegex(ValueError,'Missing native DLC texture'):collect_visual_support([path])

    @patch('l4d2_converter.native_dlc_visuals.validate_asset')
    def test_preview_fallback_and_texture_only_preview_are_reported_and_available_at_startup(self,_):
        with tempfile.TemporaryDirectory() as folder:
            stock=Path(folder)/'stock.zip';stock.write_bytes(aligned_zip({
                'materials/vgui/maps/c8.360.vtf':b'campaign',
                'materials/vgui/maps/sewers.360.vtf':b'sewers'}))
            dlc=Path(folder)/'dlc.zip';dlc.write_bytes(aligned_zip({'unrelated.txt':b'keep'}))
            mission=b'mission { Image "maps/c8" modes { coop { 1 { Image "maps/sewers" } 2 { Image "maps/rooftop" } } survival { 1 { Image "maps/rooftop" } } } }'
            members,report=collect_visual_support([dlc],stock_archives=[stock],missions=[mission])
            self.assertEqual(len(report['chapter_preview_fallbacks']),1)
            self.assertEqual(report['chapter_preview_fallbacks'][0]['material'],'materials/vgui/maps/rooftop.vmt')
            self.assertEqual({v for n,v in members.items() if n.endswith('.vtf')},{b'campaign',b'sewers'})
            self.assertIn('materials/vgui/maps/rooftop.vmt',startup_visual_members(members))
            self.assertEqual(startup_visual_members(members),members)

    @patch('l4d2_converter.native_dlc_visuals.validate_asset')
    def test_startup_includes_actual_rotary_replacement_and_its_two_texture_dependencies(self,_):
        with tempfile.TemporaryDirectory() as folder:
            path=self.archive(folder,'dlc.zip',b'native')
            members,_=collect_visual_support([path]);startup=startup_visual_members(members)
            self.assertEqual(startup[MINIGUN],members[MINIGUN])
            self.assertEqual(len([n for n in startup if n.startswith('materials/leave2/native_dlc/minigun/')]),2)

    @patch('l4d2_converter.native_dlc_visuals.validate_asset')
    def test_previous_generated_fallback_does_not_hide_recoverable_pc_thumbnail(self,_):
        with tempfile.TemporaryDirectory() as folder:
            stock=Path(folder)/'stock.zip';stock.write_bytes(aligned_zip({
                'materials/vgui/maps/c8.360.vtf':b'campaign',
                'materials/vgui/maps/rooftop.vmt':b'UnlitGeneric { "$basetexture" "leave2/native_dlc/previews/old_campaign_alias" }'}))
            dlc=Path(folder)/'dlc.zip';dlc.write_bytes(aligned_zip({'unrelated.txt':b'keep'}))
            mission=b'mission { Image "maps/c8" modes { coop { 1 { Image "maps/rooftop" } } } }'
            _,before=collect_visual_support([dlc],stock_archives=[stock],missions=[mission])
            self.assertEqual(len(before['chapter_preview_fallbacks']),1)
            members,after=collect_visual_support([dlc],stock_archives=[stock],missions=[mission],
                preview_textures={'materials/vgui/maps/rooftop.360.vtf':b'actual_rooftop'})
            self.assertEqual(after['chapter_preview_fallbacks'],[])
            self.assertTrue(after['pc_assets_used'])
            self.assertIn(b'actual_rooftop',[v for n,v in members.items() if n.endswith('.vtf')])
            self.assertNotIn(b'old_campaign_alias',members['materials/vgui/maps/rooftop.vmt'])
