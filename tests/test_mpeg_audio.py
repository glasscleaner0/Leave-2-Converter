import unittest,tempfile,hashlib
from pathlib import Path
from unittest.mock import patch
from l4d2_converter.mpeg_audio import replace_literals,prepare_mpeg_audio
class MpegPaths(unittest.TestCase):
    def test_exact_paths_and_source_sound_prefix(self):
        src=b'"message" "#eastereggs/a.mp3" "wave" "sound/eastereggs/a.mp3" "other" "prefix/eastereggs/a.mp3"'
        out,count=replace_literals(src,'eastereggs/a.mp3','eastereggs/a.wav')
        self.assertEqual(count,2)
        self.assertIn(b'"#eastereggs/a.wav"',out)
        self.assertIn(b'"sound/eastereggs/a.wav"',out)
        self.assertIn(b'"prefix/eastereggs/a.mp3"',out)
    def test_case_and_no_partial_matching(self):
        out,count=replace_literals(b'"EG/A.MP3" "eg/a.mp3.bak"','eg/a.mp3','eg/a.wav')
        self.assertEqual(count,1);self.assertIn(b'"eg/a.mp3.bak"',out)
    def test_backslash_paths_and_level_sound_references(self):
        out,count=replace_literals(b'"@#sound\\sblitz\\apt_radio.mp3" "sblitz/apt_radio.wav"','sblitz/apt_radio.mp3','sblitz/unique.wav')
        self.assertEqual(count,1);self.assertIn(b'"@#sound\\sblitz/unique.wav"',out)
        self.assertIn(b'"sblitz/apt_radio.wav"',out)

    def fixture(self,tmp,referenced=True):
        game=Path(tmp)/'game';audio=game/'sound/sblitz';audio.mkdir(parents=True)
        (audio/'apt_radio.mp3').write_bytes(b'MP3 source');(audio/'apt_radio.wav').write_bytes(b'Existing WAV content')
        owner=game/'maps/test_level_sounds.txt';owner.parent.mkdir()
        owner.write_bytes(b'"radio" { "wave" "sblitz/apt_radio.mp3" }' if referenced else b'"wave" "sblitz/apt_radio.wav"')
        return game,audio,owner

    @staticmethod
    def decode(source,scratch,decoder,timeout):
        digest=hashlib.sha256(source.read_bytes()).hexdigest();scratch=Path(scratch);scratch.mkdir(exist_ok=True)
        (scratch/(digest+'.wav')).write_bytes(b'Decoded MP3 WAV')
        return b'converted XWV',{'method':'test decoder'}

    def test_collision_retains_original_wav_and_updates_only_mp3_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            game,audio,owner=self.fixture(tmp)
            owner.write_bytes(owner.read_bytes()+b'\n"original" { "wave" "sblitz/apt_radio.wav" }')
            digest=hashlib.sha256(b'MP3 source').hexdigest()
            reserved=audio/('apt_radio_l2c_mp3_'+digest[:12]+'.wav');reserved.write_bytes(b'User reserved filename')
            with patch('l4d2_converter.mpeg_audio.fallback_xwv',side_effect=self.decode):
                rows=prepare_mpeg_audio(game,Path(tmp)/'scratch')
            self.assertEqual(len(rows),1);row=rows[0]
            self.assertTrue(row['collision_resolved_with_unique_name'])
            self.assertTrue(row['output_source'].endswith('_2.wav'))
            self.assertEqual((audio/'apt_radio.wav').read_bytes(),b'Existing WAV content')
            self.assertEqual(reserved.read_bytes(),b'User reserved filename')
            self.assertEqual((game/row['output_source']).read_bytes(),b'Decoded MP3 WAV')
            self.assertIn(b'"sblitz/apt_radio.wav"',owner.read_bytes())
            self.assertNotIn(b'apt_radio.mp3',owner.read_bytes())

    def test_unreferenced_mp3_is_preserved_as_wav_not_left_as_unsupported(self):
        with tempfile.TemporaryDirectory() as tmp:
            game,audio,owner=self.fixture(tmp,False)
            with patch('l4d2_converter.mpeg_audio.fallback_xwv',side_effect=self.decode):
                rows=prepare_mpeg_audio(game,Path(tmp)/'scratch')
            self.assertEqual(len(rows),1);self.assertTrue(rows[0]['no_direct_references_found'])
            self.assertFalse((audio/'apt_radio.mp3').exists())
            self.assertEqual((game/rows[0]['output_source']).read_bytes(),b'Decoded MP3 WAV')
            self.assertEqual((audio/'apt_radio.wav').read_bytes(),b'Existing WAV content')

    def test_failed_decode_leaves_staged_sources_and_references_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            game,audio,owner=self.fixture(tmp);before=owner.read_bytes()
            with patch('l4d2_converter.mpeg_audio.fallback_xwv',side_effect=ValueError('decode failed')):
                with self.assertRaisesRegex(ValueError,'decode failed'):prepare_mpeg_audio(game,Path(tmp)/'scratch')
            self.assertEqual(owner.read_bytes(),before);self.assertTrue((audio/'apt_radio.mp3').exists())
            self.assertEqual((audio/'apt_radio.wav').read_bytes(),b'Existing WAV content')
