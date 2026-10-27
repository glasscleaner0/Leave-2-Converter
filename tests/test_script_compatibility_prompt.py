import tempfile,unittest
from pathlib import Path
from l4d2_converter.script_compatibility import finale_rule_lines,repair_finale_rules
from l4d2_converter.scripts import transform,decode_script

class FinalePrompt(unittest.TestCase):
    def test_only_exact_executable_setting_line(self):
        data=b'// SpawnSetRule = SPAWN_FINALE\n/*\nSpawnSetRule = SPAWN_FINALE\n*/\nlocal s = "SpawnSetRule = SPAWN_FINALE"\nSpawnSetRule = SPAWN_FINALE_EXTRA\nlocal SpawnSetRule = SPAWN_FINALE\n  SpawnSetRule = SPAWN_FINALE, // incompatible\n'
        self.assertEqual([r['line'] for r in finale_rule_lines(data)],[8])
    def test_accept_decline_and_encrypted_script(self):
        for encrypted in (False,True):
            with self.subTest(encrypted=encrypted),tempfile.TemporaryDirectory() as tmp:
                game=Path(tmp);p=game/('scripts/vscripts/test.nuc' if encrypted else 'scripts/vscripts/test.nut');p.parent.mkdir(parents=True)
                plain=b'DirectorOptions <- {\r\n SpawnSetRule = SPAWN_FINALE,\r\n Other = 5\r\n}\r\n'
                original=transform(plain,decrypt=False) if encrypted else plain;p.write_bytes(original)
                records=repair_finale_rules(game,lambda rows:False)
                self.assertEqual(p.read_bytes(),original);self.assertEqual(records[0]['action'],'kept')
                prompts=[]
                records=repair_finale_rules(game,lambda rows:prompts.append(rows) or True)
                self.assertEqual(len(prompts),1);self.assertEqual(records[0]['action'],'removed')
                output=decode_script(p.read_bytes()) if encrypted else p.read_bytes()
                self.assertEqual(output,plain.replace(b' SpawnSetRule = SPAWN_FINALE,',b''))
    def test_no_prompt_means_no_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            game=Path(tmp);p=game/'scripts/vscripts/a.nut';p.parent.mkdir(parents=True);p.write_bytes(b'SpawnSetRule = SPAWN_FINALE\n')
            self.assertEqual(repair_finale_rules(game)[0]['action'],'kept')
            with self.assertRaises(InterruptedError):repair_finale_rules(game,lambda _:True,lambda:True)
            self.assertIn(b'SPAWN_FINALE',p.read_bytes())

if __name__=='__main__':unittest.main()
