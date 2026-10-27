from pathlib import Path
import hashlib,json,tempfile,unittest
from unittest.mock import patch
from l4d2_converter.offline_dlc import build_offline_dlc,install_prepared_dlc,native_offline_mission,NAME
from l4d2_converter.dlc import campaign_mission,menu_resources
from l4d2_converter.keyvalues import prepare_mission,parse,Token

class OfflineDlc(unittest.TestCase):
    def test_final_map_lookup_retains_original_identity_without_dlc_flags(self):
        original=b'mission { Name L4D2C8 BuiltIn 1 x360ctx 10 dlcmask 4 survivor_set 1 modes { coop { 1 { Map c8m1_apartment } } } }'
        result=native_offline_mission(original)
        fields={e.key.value.lower():e.value.value for e in parse(result.decode())[0].value if isinstance(e.value,Token)}
        self.assertEqual(fields['name'],'L4D2C8');self.assertEqual(fields['builtin'],'1');self.assertEqual(fields['x360ctx'],'10')
        self.assertEqual(fields['dlcmask'],'0x0000000000000000');self.assertEqual(fields['dlcrequired'],'0')
        self.assertIn(b'Map c8m1_apartment',result)
        self.assertEqual(native_offline_mission(result),result)
    def test_stock_dropdown_inheritance_is_supported(self):
        class Refs:
            def xbox_read(self,name):
                if name.endswith('dropdownmission.res'):return b'"Menu" { "ControlName" "L4D360HybridButton" }'
                return b'#base "dropdownmission.res"\r\n'
        menus=menu_resources(Refs(),{8:{'modes':['coop','versus']}})
        self.assertIn(b'cmd_campaign_l2pcc8',menus['resource/ui/l4d360ui/dropdownmissionversus.res'])
        self.assertIn(b'No Mercy',menus['resource/ui/l4d360ui/dropdownmission.res'])
    def test_native_mission_is_custom_without_changing_map_names(self):
        original=b'mission { Name L4D2C8 BuiltIn 1 x360ctx 10 dlcmask 4 survivor_set 1 modes { coop { 1 { Map c8m1_apartment } } } }'
        _,prepared=prepare_mission(original);mission,maps=campaign_mission(prepared,8)
        fields={e.key.value.lower():e.value.value for e in parse(mission.decode())[0].value if isinstance(e.value,Token)}
        self.assertEqual(maps,['c8m1_apartment']);self.assertEqual(fields['name'],'l2pcc8')
        self.assertEqual(fields['builtin'],'0');self.assertEqual(fields['survivor_set'],'1')
        self.assertEqual(fields['dlcmask'],'0x0000000000000000')
    def test_unpatched_game_refuses_before_output_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'out'
            with self.assertRaisesRegex(ValueError,'already patched'):build_offline_dlc(root,['source'],out,'exe')
            self.assertFalse(out.exists())
    def fixture(self,tmp):
        root=Path(tmp);game=root/'game';base=game/'left4dead2';(base/'bin').mkdir(parents=True)
        (base/'bin/Leave2loader_version.txt').write_text('version 1')
        state=base/'addonlist.txt';state.write_bytes(b'"AddonList" { "Custom Survivor" "1" "Other" "0" }')
        out=root/'build';addon=out/'Addons'/NAME;addon.mkdir(parents=True)
        assets={'zip0.360.zip':b'native','addoninfo.txt':b'metadata'}
        for n,d in assets.items():(addon/n).write_bytes(d)
        h=lambda b:hashlib.sha256(b).hexdigest()
        report={'status':'built-awaiting-console-test','archives':[],'maps':[],
            'generated_files':{'addoninfo.txt':h(assets['addoninfo.txt'])},'menu_mission_archive':{'file':'zip0.360.zip','sha256':h(assets['zip0.360.zip'])},'campaigns':{'8':{'title':'No Mercy'}}}
        from l4d2_converter.survivor_requirements import CREW
        crew=out/'Addons'/CREW;crew.mkdir();(crew/'zip0.360.zip').write_bytes(b'crew');(crew/'addoninfo.txt').write_bytes(b'crew metadata')
        receipt={'kind':'native-l4d1-survivors','revision':2,'files':{p.name:h(p.read_bytes()) for p in crew.iterdir()},'assets':[]}
        (crew/'leave2-survivors.json').write_text(json.dumps(receipt))
        report['required_survivor_support']={'folder':CREW,'revision':2,'files':{p.name:h(p.read_bytes()) for p in crew.iterdir()}}
        (out/'report.json').write_text(json.dumps(report));(addon/'offline-dlc-manifest.json').write_text(json.dumps(report))
        return game,out,state,addon
    @patch('l4d2_converter.loader_patcher.emulator_running',return_value=False)
    def test_installs_baseline_and_preserves_choices(self,_):
        with tempfile.TemporaryDirectory() as tmp:
            game,out,state,addon=self.fixture(tmp);before=state.read_bytes()
            result=install_prepared_dlc(game,out)
            self.assertEqual(Path(result['backup']).read_bytes(),before)
            after=state.read_text();self.assertLess(after.index(NAME),after.index('Custom Survivor'))
            from l4d2_converter.survivor_requirements import CREW
            self.assertLess(after.index(NAME),after.index(CREW));self.assertLess(after.index(CREW),after.index('Custom Survivor'))
            self.assertTrue((game/'left4dead2/addons'/CREW/'zip0.360.zip').is_file())
            self.assertIn('"Other" "0"',after);self.assertIn('"Custom Survivor" "1"',after)
            with self.assertRaisesRegex(ValueError,'already exists'):install_prepared_dlc(game,out)
    @patch('l4d2_converter.loader_patcher.emulator_running',return_value=False)
    def test_conflicting_pc_runtime_stops_without_state_change(self,_):
        with tempfile.TemporaryDirectory() as tmp:
            game,out,state,addon=self.fixture(tmp);state.write_bytes(b'"AddonList" { "PC Campaign Runtime" "1" }');before=state.read_bytes()
            with self.assertRaisesRegex(ValueError,'conflicting PC addons'):install_prepared_dlc(game,out)
            self.assertEqual(before,state.read_bytes());self.assertFalse((game/'left4dead2/addons'/NAME).exists())
    @patch('l4d2_converter.loader_patcher.emulator_running',return_value=False)
    def test_modified_build_cannot_be_installed(self,_):
        with tempfile.TemporaryDirectory() as tmp:
            game,out,state,addon=self.fixture(tmp);(addon/'zip0.360.zip').write_bytes(b'edited')
            with self.assertRaisesRegex(ValueError,'build changed'):install_prepared_dlc(game,out)
            self.assertFalse((game/'left4dead2/addons'/NAME).exists())
    @patch('l4d2_converter.loader_patcher.emulator_running',return_value=False)
    def test_required_crew_is_enabled_without_altering_other_choices(self,_):
        from l4d2_converter.survivor_requirements import CREW
        with tempfile.TemporaryDirectory() as tmp:
            game,out,state,addon=self.fixture(tmp)
            state.write_text('"AddonList" { "'+CREW+'" "0" "Other" "0" }')
            result=install_prepared_dlc(game,out)
            self.assertTrue(result['required_survivor_support_enabled'])
            fields={e.key.value:e.value.value for e in parse(state.read_text())[0].value}
            self.assertEqual(fields[CREW],'1');self.assertEqual(fields['Other'],'0')

if __name__=='__main__':unittest.main()
