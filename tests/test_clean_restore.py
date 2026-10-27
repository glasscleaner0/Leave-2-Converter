import json,zlib
from pathlib import Path
from unittest.mock import patch
import unittest
import test_loader_patcher as fixtures
sha=fixtures.sha

class CleanRestoreTests(unittest.TestCase):
    setUp=fixtures.PatcherTests.setUp
    snapshot=fixtures.PatcherTests.snapshot
    def mods(self):
        folder=self.game/'left4dead2/addons/My addon';folder.mkdir(parents=True,exist_ok=True)
        (folder/'zip0.360.zip').write_bytes(b'converted mod')
        (self.game/'left4dead2/addonlist.txt').write_bytes(b'saved choices')
        (self.game/'left4dead2/zip5.360.zip').write_bytes(b'startup packet')

    def restore(self):
        with patch('l4d2_converter.clean_restore.emulator_running',return_value=False):
            return self.patcher.restore_clean(self.game,acknowledge_mod_deletion=True)

    def test_acknowledgement_is_required_before_any_changes(self):
        self.patcher.apply(self.game);self.mods();before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'Acknowledge'):self.patcher.restore_clean(self.game)
        self.assertEqual(before,self.snapshot())

    def test_all_installed_addons_and_extra_archives_removed_original_files_exact(self):
        base=self.game/'left4dead2';base.mkdir();(base/'zip0.360.zip').write_bytes(b'stock0');(base/'zip1.360.zip').write_bytes(b'stock1')
        before=self.snapshot();self.mods();self.patcher.apply(self.game)
        (base/'zip17.zip').write_bytes(b'extra mod')
        outside=self.root/'converted-output';outside.mkdir();(outside/'mod.zip').write_bytes(b'keep source output')
        result=self.restore();self.assertEqual(result['status'],'restored-clean')
        self.assertEqual(before,self.snapshot());self.assertFalse((base/'addons').exists())
        self.assertEqual((outside/'mod.zip').read_bytes(),b'keep source output')
        self.assertTrue(Path(result['backup']).is_dir());self.assertFalse((self.game/'.leave2-loader/active.json').exists())

    def test_preexisting_official_update_archive_is_preserved(self):
        base=self.game/'left4dead2';base.mkdir();(base/'zip2.360.zip').write_bytes(b'new resource archive')
        before=self.snapshot();self.patcher.apply(self.game);self.mods();self.restore()
        self.assertEqual(before,self.snapshot())

    def test_tampered_backup_blocks_before_deleting_mods(self):
        result=self.patcher.apply(self.game);self.mods();before=self.snapshot()
        (Path(result['backup'])/'files/default.xex').write_bytes(b'bad backup')
        with self.assertRaisesRegex(ValueError,'Backup integrity'):self.restore()
        self.assertEqual(before,self.snapshot())

    def test_modified_module_blocks_before_deleting_mods(self):
        self.patcher.apply(self.game);self.mods();(self.game/'bin/engine.dll').write_bytes(b'modified later');before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'changed since patching'):self.restore()
        self.assertEqual(before,self.snapshot())

    def test_multiple_patch_layers_restore_the_earliest_originals(self):
        before=self.snapshot();self.patcher.apply(self.game)
        data=b'Loader version 2';(self.bundle/'marker.bin').write_bytes(zlib.compress(data))
        self.patcher.manifest['files'].append({'path':'left4dead2/bin/Leave2loader_version.txt','target_sha256':sha(data),'target_bytes':len(data),'allow_absent':True,'new_payload':'marker.bin','variants':[]})
        self.patcher.allowed.add('left4dead2/bin/leave2loader_version.txt')
        self.patcher.apply(self.game);self.mods();result=self.restore()
        self.assertEqual(result['restored_backup_layers'],2);self.assertEqual(before,self.snapshot())

    def test_write_failure_restores_mods_and_patched_state(self):
        self.patcher.apply(self.game);self.mods();before=self.snapshot();calls=[];original=self.patcher._replace
        def fail(root,name,data):
            calls.append(name)
            if len(calls)==2:raise OSError('injected restore failure')
            original(root,name,data)
        with patch.object(self.patcher,'_replace',side_effect=fail):
            with self.assertRaisesRegex(OSError,'injected'):self.restore()
        self.assertEqual(before,self.snapshot());self.assertTrue((self.game/'.leave2-loader/active.json').is_file())

    def test_cleanup_failure_is_reported_without_claiming_mods_permanently_deleted(self):
        self.patcher.apply(self.game);self.mods()
        with patch('l4d2_converter.clean_restore.shutil.rmtree',side_effect=PermissionError('locked')):
            result=self.restore()
        self.assertEqual(result['status'],'restored-clean-cleanup-required')
        self.assertTrue(Path(result['cleanup_pending']).is_dir());self.assertFalse((self.game/'left4dead2/addons').exists())

    def test_failed_recovery_preserves_quarantined_mods_and_blocks_repatching(self):
        self.patcher.apply(self.game);self.mods();calls=[];original=self.patcher._replace
        def fail(root,name,data):
            calls.append(name)
            if len(calls)>=2:raise OSError('injected persistent write failure')
            original(root,name,data)
        with patch.object(self.patcher,'_replace',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'needs recovery'):self.restore()
        record=json.loads((self.game/'.leave2-loader/clean-restore-recovery.json').read_text())
        self.assertTrue(any(p.read_bytes()==b'converted mod' for p in Path(record['trash']).rglob('zip0.360.zip')))
        with self.assertRaisesRegex(ValueError,'needs recovery'):self.patcher.inspect(self.game)
