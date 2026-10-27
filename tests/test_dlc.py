import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import subprocess
from l4d2_converter.dlc import campaign_selection,campaign_mission,menu_resources,stage_campaign,pc_asset,console_poster,DlcOptions,convert_dlc
from l4d2_converter.keyvalues import parse,Token

MISSION=b'"mission" { "Name" "L4D2C9" "BuiltIn" "1" "dlcmask" "4" "modes" { "coop" { "1" { "Map" "c9m1_alleys" } } } }'

def bsp():
    data=bytearray(1036);data[:8]=b'VBSP'+struct.pack('<I',20);entity=b'{ "classname" "worldspawn" }\0'
    struct.pack_into('<4I',data,8,1036,len(entity),0,0)
    return bytes(data)+entity

class DlcCampaigns(unittest.TestCase):
    def test_selection_is_exact_and_excludes_last_stand(self):
        self.assertEqual(campaign_selection((13,6)),(6,13))
        for values in ((),(14,),(6,6),(True,)):
            with self.assertRaises(ValueError):campaign_selection(values)

    def test_namespaced_mission_preserves_map_and_transition_names(self):
        data,maps=campaign_mission(MISSION,9)
        self.assertIn(b'"l2pcc9"',data);self.assertEqual(maps,['c9m1_alleys'])
        fields={e.key.value.lower():e.value.value for e in parse(data.decode())[0].value if isinstance(e.value,Token)}
        self.assertRegex(fields['name'],r'^[A-Za-z0-9]+$')
        self.assertIn(b'"BuiltIn" "1"',data) # Core performs its usual mission adaptation later.
        with self.assertRaises(ValueError):campaign_mission(MISSION,8)
        with self.assertRaises(ValueError):campaign_mission(MISSION.replace(b'c9m1_alleys',b'c1m1_hotel'),9)

    def test_loose_update_precedes_archive_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'update/scripts/file.nut';p.parent.mkdir(parents=True);p.write_bytes(b'updated')
            refs=SimpleNamespace(pc_root=root,pc_read=lambda n:b'old archive')
            self.assertEqual(pc_asset(refs,'scripts/file.nut')[0],b'updated')
            with self.assertRaises(ValueError):pc_asset(refs,'../secret')

    def test_source_collection_is_scoped_and_reports_unapplied_overlays(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'pc';p=source/'update/maps/c9m1_alleys_h_0.lmp';p.parent.mkdir(parents=True);p.write_bytes(b'overlay')
            files={'missions/campaign9.txt':MISSION,'maps/c9m1_alleys.bsp':bsp(),'maps/c9m1_alleys.nav':b'nav','scripts/vscripts/c9m1_event.nut':b'// event','scripts/vscripts/c14_other.nut':b'// excluded'}
            refs=SimpleNamespace(pc_root=source,pc=files,xbox={},pc_read=lambda n:files.get(n))
            out=root/'collected'
            with patch('l4d2_converter.compatibility.apply_repairs',return_value=[]),patch('l4d2_converter.dependencies.discover',return_value={'missing':[]}),patch('l4d2_converter.compatibility.recover_internal_material_aliases',return_value=[]):
                report=stage_campaign(refs,9,out)
            self.assertTrue((out/'maps/c9m1_alleys.bsp').is_file());self.assertTrue((out/'scripts/vscripts/c9m1_event.nut').is_file())
            self.assertFalse((out/'scripts/vscripts/c14_other.nut').exists());self.assertFalse(list(out.rglob('*.lmp')))
            self.assertEqual(report['pc_entity_overlays'][0]['status'],'not-applied');self.assertTrue(report['warnings'])
            self.assertEqual(p.read_bytes(),b'overlay')

    def test_menu_changes_only_ready_routes_and_keeps_vanilla_buttons(self):
        refs=SimpleNamespace(xbox_read=lambda n:b'L4D360HybridButton')
        resources=menu_resources(refs,{9:{'modes':['coop']},13:{'modes':['coop','versus']}})
        self.assertEqual(len(resources),16)
        import re
        for payload in resources.values():
            for identifier in re.findall(rb'cmd_campaign_([^\"\s]*)',payload):
                self.assertTrue(not identifier or re.fullmatch(rb'[A-Za-z0-9]+',identifier),identifier)
        text=resources['resource/ui/l4d360ui/dropdownmission.res'].decode()
        self.assertIn('cmd_campaign_l2pcc9',text);self.assertIn('cmd_campaign_l2pcc13',text)
        self.assertIn('cmd_campaign_L4D2C1',text);self.assertIn('cmd_addoncampaign',text)
        self.assertNotIn('L4D2C14',text);self.assertNotIn('cmd_campaign_l2pcc6',text)
        alias=resources['resource/ui/l4d360ui/addonbase_dropdownmission.res'].decode()
        self.assertIn('cmd_campaign_l2pcc9',alias)
        self.assertIn('addonbase_dropdownmission.res',alias)
        versus=resources['resource/ui/l4d360ui/dropdownmissionversus.res'].decode()
        self.assertNotIn('cmd_campaign_l2pcc9',versus)
        self.assertNotIn('cmd_campaign_L4D2C9',versus)
        for mode in ('survival','scavenge'):
            for extended in ('','extended'):
                for prefix in ('','addonbase_'):
                    resource=resources['resource/ui/l4d360ui/'+prefix+'dropdownmission'+mode+extended+'.res']
                    for number in (9,13):
                        self.assertNotIn(('cmd_campaign_L4D2C'+str(number)+'"').encode(),resource)
                        self.assertNotIn(('cmd_campaign_l2pcc'+str(number)+'"').encode(),resource)
        root=parse(text);blocks={e.key.value:e.value for e in root[0].value if isinstance(e.value,list)}
        for name,fields in blocks.items():
            if not name.startswith('Btn'):continue
            for e in fields:
                if e.key.value in ('navUp','navDown'):self.assertIn(e.value.value,blocks)
        self.assertFalse(menu_resources(refs,{}))

    def test_offline_modes_keep_only_their_available_campaigns_and_valid_navigation(self):
        refs=SimpleNamespace(xbox_read=lambda n:b'L4D360HybridButton')
        resources=menu_resources(refs,{8:{'modes':['coop','versus','survival','scavenge']},
                                      9:{'modes':['coop','versus']},10:{'modes':['coop','versus','scavenge']}})
        for mode in ('survival','scavenge'):
            text=resources['resource/ui/l4d360ui/dropdownmission'+mode+'.res'].decode()
            self.assertIn('cmd_campaign_l2pcc8',text)
            self.assertNotIn('cmd_campaign_L4D2C8',text)
            self.assertNotIn('Crash Course',text)
            if mode=='survival':self.assertNotIn('Death Toll',text)
            else:self.assertIn('cmd_campaign_l2pcc10',text)
            blocks={e.key.value:e.value for e in parse(text)[0].value if isinstance(e.value,list)}
            for name,fields in blocks.items():
                if not name.startswith('Btn'):continue
                for e in fields:
                    if e.key.value in ('navUp','navDown'):self.assertIn(e.value.value,blocks)

class SdkTexturePaths(unittest.TestCase):
    def test_non_ascii_texture_gets_short_ascii_sdk_alias(self):
        from l4d2_converter.core import texture_alias_reason
        self.assertEqual(texture_alias_reason('materials/dons_decals/serviet bug'+chr(233)+'.vtf',Path('game')),'ascii_sdk_texture_path')
        self.assertIsNone(texture_alias_reason('materials/normal.vtf',Path('game')))

class PosterAdapter(unittest.TestCase):
    def poster(self,fmt=13):
        header=bytearray(80);header[:4]=b'VTF\0';struct.pack_into('<3I',header,4,7,2,80)
        struct.pack_into('<2H',header,16,2048,512);struct.pack_into('<H',header,24,1)
        struct.pack_into('<I',header,52,fmt);header[56]=1;struct.pack_into('<I',header,57,0xffffffff);struct.pack_into('<H',header,63,1)
        return bytes(header)+bytes(2048*512//2)

    def test_resize_uses_real_dds_file_and_cleans_temporary_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            decoder=Path(tmp)/'ffmpeg.exe';decoder.touch()
            def run(args,**kwargs):
                source=Path(args[args.index('-i')+1]);self.assertTrue(source.is_file())
                data=source.read_bytes();self.assertEqual(data[:4],b'DDS ');self.assertEqual(data[84:88],b'DXT1')
                self.assertEqual(len(data),128+2048*512//2)
                return subprocess.CompletedProcess(args,0,bytes(512*128*4),b'')
            with patch('l4d2_converter.dlc.subprocess.run',side_effect=run):
                result,report=console_poster(self.poster(),str(decoder),tmp)
            self.assertEqual(struct.unpack_from('<2H',result,16),(512,128))
            self.assertEqual(report['after'],[512,128]);self.assertEqual(list(Path(tmp).iterdir()),[decoder])

    def test_missing_decoder_and_unsupported_input_remain_explicit_failures(self):
        with self.assertRaisesRegex(ValueError,'FFmpeg'):console_poster(self.poster(),'',None)
        with self.assertRaisesRegex(ValueError,'Unsupported'):console_poster(self.poster(fmt=999),'',None)

class DlcBatch(unittest.TestCase):
    def test_partial_build_publishes_only_successful_campaign_and_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pc=root/'pc';(pc/'left4dead2').mkdir(parents=True)
            options=DlcOptions(pc_game=str(pc),output=str(root/'output'),sdk_bin=str(root/'sdk'),xbox_game=str(root/'xbox'),campaigns=(6,7))
            def stage(refs,number,destination,*args):
                destination.mkdir(parents=True);return {'modes':['coop'],'maps':['dummy']}
            def convert(options,**kwargs):
                if options.input.endswith('c6'):return {'status':'failed','failures':[{'reason':'missing file'}]}
                folder=Path(options.output)/'Success';folder.mkdir(parents=True);(folder/'zip0.360.zip').write_bytes(b'game assets')
                return {'status':'converted-awaiting-console-test','leave2_loader':{'folder':'Success'}}
            refs=SimpleNamespace(xbox_read=lambda n:b'L4D360HybridButton')
            with patch('l4d2_converter.dlc.References',return_value=refs),patch('l4d2_converter.dlc.stage_campaign',side_effect=stage),patch('l4d2_converter.dlc.convert',side_effect=convert),patch('l4d2_converter.dlc.build_population_runtime',return_value={'folder':'Addons/PC Campaign Runtime'}) as runtime:
                report=convert_dlc(options,progress=lambda s:None)
            self.assertEqual(set(runtime.call_args.args[1]),{7})
            self.assertEqual(report['population_runtime']['folder'],'Addons/PC Campaign Runtime')
            self.assertEqual(report['status'],'partial');self.assertEqual(report['menu']['campaigns'],[7])
            self.assertTrue((root/'output/Addons/Success/zip0.360.zip').is_file())
            self.assertEqual(json.loads((root/'output/report.json').read_text())['status'],'partial')
            self.assertEqual(len(report['failures']),1)

if __name__=='__main__':unittest.main()
class AchievementAssets(unittest.TestCase):
    def test_campaign_pack_scope_and_material_texture_pairs(self):
        from l4d2_converter.dlc import achievement_asset_names
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for folder in ('left4dead2_dlc1','left4dead2_dlc2','left4dead2_dlc3'):
                p=root/folder/'pak01_dir.vpk';p.parent.mkdir();p.touch()
            def archive(path):
                tag=path.parent.name
                return SimpleNamespace(entries={f'materials/vgui/achievements/{tag}.vmt':None,
                    f'materials/vgui/achievements/{tag}.vtf':None,'materials/unrelated.vtf':None})
            refs=SimpleNamespace(pc_root=root)
            with patch('l4d2_converter.dlc.Vpk',side_effect=archive):
                for campaign,folder in ((6,'left4dead2_dlc1'),(7,'left4dead2_dlc2'),(8,'left4dead2_dlc2'),(12,'left4dead2_dlc2'),(13,'left4dead2_dlc3')):
                    names=achievement_asset_names(refs,campaign)
                    self.assertEqual(names,[f'materials/vgui/achievements/{folder}.vmt',f'materials/vgui/achievements/{folder}.vtf'])
    def test_loose_icons_are_included_without_symlink_or_unrelated_files(self):
        from l4d2_converter.dlc import achievement_asset_names
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'left4dead2_dlc1/materials/vgui/achievements';p.mkdir(parents=True)
            (p/'a.vmt').write_bytes(b'vmt');(p/'a.vtf').write_bytes(b'vtf');(p/'readme.txt').write_text('ignore')
            names=achievement_asset_names(SimpleNamespace(pc_root=root),6)
            self.assertEqual(names,['materials/vgui/achievements/a.vmt','materials/vgui/achievements/a.vtf'])
    def test_achievement_payloads_are_staged_and_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pc=root/'pc';pc.mkdir()
            files={'missions/campaign9.txt':MISSION,'maps/c9m1_alleys.bsp':bsp(),'maps/c9m1_alleys.nav':b'nav',
                'materials/vgui/achievements/icon.vmt':b'UnlitGeneric { "$basetexture" "vgui/achievements/icon" }',
                'materials/vgui/achievements/icon.vtf':b'original texture bytes'}
            refs=SimpleNamespace(pc_root=pc,pc=files,xbox={},pc_read=lambda n:files.get(n));dest=root/'out'
            names=[n for n in files if '/achievements/' in n]
            with patch('l4d2_converter.dlc.achievement_asset_names',return_value=names),patch('l4d2_converter.compatibility.apply_repairs',return_value=[]),patch('l4d2_converter.dependencies.discover',return_value={'missing':[]}),patch('l4d2_converter.compatibility.recover_internal_material_aliases',return_value=[]):
                report=stage_campaign(refs,9,dest)
            self.assertEqual(report['achievement_assets'],names)
            for n in names:self.assertEqual((dest/n).read_bytes(),files[n])
