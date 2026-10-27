import hashlib,json,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from l4d2_converter.archive import aligned_zip
from l4d2_converter.startup_audio import plan_startup_audio,RECEIPT


class StartupAudio(unittest.TestCase):
    def fixture(self,tmp):
        root=Path(tmp);game=root/'game';base=game/'left4dead2';base.mkdir(parents=True)
        for i in range(3):(base/f'zip{i}.360.zip').write_bytes(b'stock')
        source=root/'startup.zip';source.write_bytes(aligned_zip({'scripts/test.txt':b'data'}))
        return game,source,{'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}

    def test_chooses_next_root_slot_without_changing_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            game,source,spec=self.fixture(tmp);plan=plan_startup_audio(game,source,spec)
            self.assertEqual(plan['target'],game/'left4dead2/zip3.360.zip')
            self.assertFalse(plan['target'].exists());self.assertFalse(plan['receipt'].exists())

    def test_refuses_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            game,source,spec=self.fixture(tmp);(game/'left4dead2/zip1.360.zip').unlink()
            with self.assertRaisesRegex(ValueError,'gaps'):plan_startup_audio(game,source,spec)

    def test_modified_export_is_rejected_before_planning(self):
        with tempfile.TemporaryDirectory() as tmp:
            game,source,spec=self.fixture(tmp);source.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'build changed'):plan_startup_audio(game,source,spec)

    def test_preserves_verified_existing_registration_but_rejects_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            game,source,spec=self.fixture(tmp);plan=plan_startup_audio(game,source,spec)
            plan['target'].write_bytes(plan['payload']);plan['receipt'].parent.mkdir()
            plan['receipt'].write_bytes(plan['record'])
            self.assertIsNone(plan_startup_audio(game,source,spec))
            plan['target'].write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'Installed startup audio changed'):plan_startup_audio(game,source,spec)


class OfflineStartupTransaction(unittest.TestCase):
    def fixture(self,tmp):
        from test_offline_dlc import OfflineDlc
        game,out,state,addon=OfflineDlc().fixture(tmp)
        for i in range(3):(game/f'left4dead2/zip{i}.360.zip').write_bytes(b'stock')
        source=out/'Startup-Audio/startup-audio.360.zip';source.parent.mkdir()
        source.write_bytes(aligned_zip({'scripts/test.txt':b'data'}))
        spec={'file':'Startup-Audio/startup-audio.360.zip','sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
        report=json.loads((out/'report.json').read_text());report['startup_audio']=spec
        (out/'report.json').write_text(json.dumps(report))
        return game,out,state,addon

    @patch('l4d2_converter.loader_patcher.emulator_running',return_value=False)
    def test_installs_registration_with_dlc_and_preserves_root_archives(self,_):
        from l4d2_converter.offline_dlc import install_prepared_dlc
        with tempfile.TemporaryDirectory() as tmp:
            game,out,state,addon=self.fixture(tmp)
            result=install_prepared_dlc(game,out)
            self.assertTrue(result['startup_audio_installed'])
            self.assertTrue((game/RECEIPT).is_file())
            self.assertEqual((game/'left4dead2/zip0.360.zip').read_bytes(),b'stock')

    @patch('l4d2_converter.loader_patcher.emulator_running',return_value=False)
    def test_publication_failure_rolls_back_addons_and_startup_registration(self,_):
        import os
        from l4d2_converter.offline_dlc import install_prepared_dlc,NAME
        from l4d2_converter.survivor_requirements import CREW
        with tempfile.TemporaryDirectory() as tmp:
            game,out,state,addon=self.fixture(tmp);before=state.read_bytes();replace=os.replace
            def fail_state(src,dest):
                if Path(dest)==state:raise OSError('simulated state publication failure')
                return replace(src,dest)
            with patch('l4d2_converter.offline_dlc.os.replace',side_effect=fail_state):
                with self.assertRaisesRegex(OSError,'simulated'):install_prepared_dlc(game,out)
            self.assertEqual(state.read_bytes(),before)
            self.assertFalse((game/'left4dead2/zip3.360.zip').exists())
            self.assertFalse((game/RECEIPT).exists())
            self.assertFalse((game/'left4dead2/addons'/NAME).exists())
            self.assertFalse((game/'left4dead2/addons'/CREW).exists())
