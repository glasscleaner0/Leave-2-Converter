import tempfile,unittest,json,hashlib,zlib,struct
from pathlib import Path
from unittest.mock import patch
from l4d2_converter.loader_patcher import LoaderPatcher,safe

sha=lambda b:hashlib.sha256(b).hexdigest()
class PatcherTests(unittest.TestCase):
    def test_apply_creates_addons_and_recreates_when_already_patched(self):
        folder=self.game/'left4dead2/addons'
        self.patcher.inspect(self.game);self.assertFalse(folder.exists())
        self.patcher.apply(self.game);self.assertTrue(folder.is_dir())
        folder.rmdir();self.patcher.apply(self.game);self.assertTrue(folder.is_dir())
        (folder/'mine.txt').write_text('keep')
        self.patcher.apply(self.game);self.assertEqual((folder/'mine.txt').read_text(),'keep')
    def test_addons_file_conflict_blocks_before_any_changes(self):
        folder=self.game/'left4dead2';folder.mkdir();(folder/'addons').write_bytes(b'user file')
        before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'Expected an addons folder'):self.patcher.apply(self.game)
        self.assertEqual(before,self.snapshot())
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.game=self.root/'game';self.game.mkdir();self.bundle=self.root/'bundle';self.bundle.mkdir()
        files=[]
        for i,(name,old,new) in enumerate([('default.xex',b'clean executable',b'updated executable'),('bin/engine.dll',b'original engine',b'loader engine'),('left4dead2/zip2.360.zip',None,b'new resource archive')]):
            f={'path':name,'target_sha256':sha(new),'target_bytes':len(new),'allow_absent':old is None,'variants':[]}
            if old is not None:
                p=self.game/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(old)
                xor=bytes(a^b for a,b in zip(new,old[:len(new)]+bytes(max(0,len(new)-len(old)))))
                payload=b'L2XOR1\0'+struct.pack('<Q',len(new))+zlib.compress(xor);key=str(i)+'.xor';(self.bundle/key).write_bytes(payload)
                f['variants']=[{'source_sha256':sha(old),'source_bytes':len(old),'payload':key,'payload_sha256':sha(payload)}]
            else:key=str(i)+'.bin';(self.bundle/key).write_bytes(zlib.compress(new));f['new_payload']=key
            files.append(f)
        (self.bundle/'manifest.json').write_text(json.dumps({'schema':1,'patch_id':'test','files':files}))
        self.patcher=LoaderPatcher(self.bundle)
        self.addCleanup(patch.stopall);patch('l4d2_converter.loader_patcher.emulator_running',return_value=False).start()
    def snapshot(self):return {p.relative_to(self.game).as_posix():p.read_bytes() for p in self.game.rglob('*') if p.is_file() and '.leave2-loader' not in p.parts}
    def test_check_is_read_only_and_unrelated_mods_are_allowed(self):
        p=self.game/'left4dead2';p.mkdir();(p/'gameinfo.xtx').write_bytes(b'user configuration');(p/'zip0.zip').write_bytes(b'user archive')
        before=self.snapshot();self.assertEqual(self.patcher.inspect(self.game)['status'],'ready');self.assertEqual(before,self.snapshot());self.assertFalse((self.game/'.leave2-loader').exists())
    def test_apply_restore_and_saved_addons_untouched(self):
        folder=self.game/'left4dead2/addons/user';folder.mkdir(parents=True);(folder/'own.txt').write_bytes(b'addon')
        (folder.parent.parent/'addonlist.txt').write_bytes(b'user saved choices');before=self.snapshot()
        result=self.patcher.apply(self.game);self.assertEqual(result['status'],'installed');self.assertEqual(self.patcher.inspect(self.game)['status'],'already-installed')
        self.assertEqual(self.patcher.apply(self.game)['status'],'already-installed')
        self.assertEqual(self.patcher.restore(self.game)['status'],'restored');self.assertEqual(before,self.snapshot());self.assertTrue(Path(result['backup']).is_dir())
    def test_only_modified_patch_target_rejected_before_writes(self):
        (self.game/'bin/engine.dll').write_bytes(b'unrecognized modification');before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'Unknown or modified'):self.patcher.apply(self.game)
        self.assertEqual(before,self.snapshot());self.assertFalse((self.game/'.leave2-loader').exists())
    def test_new_archive_conflict_is_not_overwritten(self):
        p=self.game/'left4dead2';p.mkdir();(p/'zip2.360.zip').write_bytes(b'some addon');before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'archive conflict'):self.patcher.apply(self.game)
        self.assertEqual(before,self.snapshot())
    def test_tampered_patch_rejected(self):
        (self.bundle/'0.xor').write_bytes(b'broken');before=self.snapshot()
        with self.assertRaises(ValueError):self.patcher.apply(self.game)
        self.assertEqual(before,self.snapshot())
    def test_mid_install_failure_rolls_back(self):
        original=self.patcher._replace;calls=[];before=self.snapshot()
        def fail(root,name,data):
            calls.append(name)
            if len(calls)==2:raise OSError('injected commit failure')
            original(root,name,data)
        with patch.object(self.patcher,'_replace',side_effect=fail):
            with self.assertRaisesRegex(OSError,'injected'):self.patcher.apply(self.game)
        self.assertEqual(before,self.snapshot());self.assertFalse((self.game/'.leave2-loader/operation.lock').exists())
    def test_modified_installed_file_blocks_restore(self):
        self.patcher.apply(self.game);(self.game/'bin/engine.dll').write_bytes(b'new user edit');before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'changed since patching'):self.patcher.restore(self.game)
        self.assertEqual(before,self.snapshot())
    def test_tampered_backup_blocks_restore(self):
        result=self.patcher.apply(self.game);(Path(result['backup'])/'files/default.xex').write_bytes(b'broken');before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'Backup integrity'):self.patcher.restore(self.game)
        self.assertEqual(before,self.snapshot())
    def test_running_emulator_blocks_writes(self):
        before=self.snapshot()
        with patch('l4d2_converter.loader_patcher.emulator_running',return_value=True):
            with self.assertRaisesRegex(ValueError,'Close Xenia'):self.patcher.apply(self.game)
        self.assertEqual(before,self.snapshot())
    def test_path_escape_rejected(self):
        for name in ('../bad','/absolute','bin/../../bad','C:/bad'):
            with self.assertRaises(ValueError):safe(self.game,name)
    def test_updated_game_preserves_modified_non_loader_module(self):
        j=self.patcher.manifest;j['profile_support']=True
        j['files'][1].update(loader_module=True,official_sha256=sha(b'original engine'))
        j['files'].append({'path':'bin/client.dll','target_sha256':sha(b'official client'),'variants':[],'target_bytes':15,'allow_absent':False})
        (self.game/'default.xex').write_bytes(b'updated executable');(self.game/'bin/client.dll').write_bytes(b'custom unrelated client')
        self.assertEqual(set(self.patcher.inspect(self.game)['changed_files']),{'bin/engine.dll','left4dead2/zip2.360.zip'})
        self.patcher.apply(self.game);self.assertEqual((self.game/'bin/client.dll').read_bytes(),b'custom unrelated client')
    def test_updated_core_does_not_reject_unrelated_executable_modification(self):
        self.patcher.manifest['profile_support']=True
        self.patcher.manifest['files'][1].update(loader_module=True,official_sha256=sha(b'original engine'))
        (self.game/'default.xex').write_bytes(b'user-modified executable')
        self.patcher.apply(self.game);self.assertEqual((self.game/'default.xex').read_bytes(),b'user-modified executable')
    def test_later_version_marker_keeps_original_backup_reachable(self):
        before=self.snapshot();first=self.patcher.apply(self.game)
        content=b'Leave 2 Loader version 1\r\n';(self.bundle/'version.bin').write_bytes(zlib.compress(content))
        self.patcher.manifest['files'].append({'path':'left4dead2/bin/Leave2loader_version.txt','target_sha256':sha(content),'target_bytes':len(content),'variants':[],'allow_absent':True,'new_payload':'version.bin','loader_marker':True})
        (self.bundle/'manifest.json').write_text(json.dumps(self.patcher.manifest));self.patcher=LoaderPatcher(self.bundle)
        second=self.patcher.apply(self.game)
        self.assertNotEqual(first['backup'],second['backup'])
        self.assertEqual((self.game/'left4dead2/bin/Leave2loader_version.txt').read_bytes(),content)
        self.patcher.restore(self.game)
        active=json.loads((self.game/'.leave2-loader/active.json').read_text())
        self.assertEqual(active['backup'],Path(first['backup']).name)
        self.patcher.restore(self.game);self.assertEqual(before,self.snapshot())
