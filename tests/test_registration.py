import tempfile,unittest
from pathlib import Path
from l4d2_converter.registration import merge_registered_addons,register_installed_addons
class Registration(unittest.TestCase):
 def test_preserves_existing_states_and_does_not_duplicate_names(self):
  old=b'"AddonList" { "Existing" "0" }';new,added=merge_registered_addons(old,['existing','Cold Stream (PC Port)'])
  self.assertEqual(added,['Cold Stream (PC Port)']);self.assertIn(b'"Existing" "0"',new)
  again,added=merge_registered_addons(new,['existing','Cold Stream (PC Port)']);self.assertEqual(again,new);self.assertFalse(added)
 def test_malformed_list_is_not_replaced(self):
  with self.assertRaises(ValueError):merge_registered_addons(b'"AddonList" {',['New'])
 def test_discovers_managed_folders_and_backs_up_state(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'left4dead2';folder=root/'addons/Port';folder.mkdir(parents=True)
   (folder/'addoninfo.txt').write_text('"AddonInfo" { "leave2_managed" "1" }')
   state=root/'addonlist.txt';state.write_bytes(b'"AddonList" { "Other" "0" }')
   original=state.read_bytes();result=register_installed_addons(tmp)
   self.assertEqual(result['added'],['Port']);self.assertEqual(Path(result['backup']).read_bytes(),original)
   self.assertIn(b'"Other" "0"',state.read_bytes());self.assertIn(b'"Port" "1"',state.read_bytes())
if __name__=='__main__':unittest.main()

class BaselinePriority(unittest.TestCase):
    def test_baselines_before_replacements_without_changing_checkboxes(self):
        from l4d2_converter.registration import order_addon_baselines
        from l4d2_converter.keyvalues import parse
        source=b'"AddonList" { "custom" "0" "campaign" "1" "other" "1" "runtime" "1" }'
        result=order_addon_baselines(source,['runtime','campaign'])
        entries=parse(result.decode())[0].value
        self.assertEqual([(e.key.value,e.value.value) for e in entries],[('runtime','1'),('campaign','1'),('custom','0'),('other','1')])
        self.assertEqual(order_addon_baselines(result,['runtime','campaign']),result)

    def test_registration_keeps_shared_repairs_above_campaigns_below_customs(self):
        import tempfile
        from pathlib import Path
        from l4d2_converter.registration import register_installed_addons
        from l4d2_converter.keyvalues import parse
        with tempfile.TemporaryDirectory() as tmp:
            game=Path(tmp);addons=game/'addons';addons.mkdir()
            for name,role in [('runtime','base_resources'),('campaign','campaign_base'),('custom','')]:
                folder=addons/name;folder.mkdir()
                (folder/'addoninfo.txt').write_text('"AddonInfo" { "leave2_managed" "1" "leave2_role" "'+role+'" }')
            (game/'addonlist.txt').write_text('"AddonList" { "custom" "0" "runtime" "1" "campaign" "1" }')
            register_installed_addons(game)
            entries=parse((game/'addonlist.txt').read_text())[0].value
            self.assertEqual([(e.key.value,e.value.value) for e in entries],[('campaign','1'),('runtime','1'),('custom','0')])
