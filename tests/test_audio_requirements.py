import unittest
from l4d2_converter.audio_requirements import audit_audio


class AudioRequirements(unittest.TestCase):
    def test_distinguishes_missing_audio_dynamic_voices_and_native_resources(self):
        members={'sound/music/test.360.wav':b'native',
                 'maps/test_level_sounds.txt':b'''"Event.Test" { "rndwave" {
                  "wave" "@#music/test.wav" "wave" "music/missing.wav"
                  "wave" "music/native.wav" "wave" "player/survivor/voice/$survivor/Fall01.wav" } }'''}
        report,warnings=audit_audio(members,['sound/music/native.360.wav'])
        self.assertEqual(report['missing_declared_waves'],['sound/music/missing.wav'])
        self.assertEqual(len(report['dynamic_survivor_wave_paths']),1)
        self.assertEqual(report['loader_audio_revision_recommended'],1)
        self.assertFalse(report['audio_rewritten_by_audit'])
        self.assertEqual(len(warnings),2)

    def test_texture_addon_has_no_new_audio_requirement(self):
        report,warnings=audit_audio({'materials/test.360.vtf':b'texture'})
        self.assertIsNone(report['loader_audio_revision_recommended'])
        self.assertEqual(warnings,[])
