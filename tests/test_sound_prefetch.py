import unittest
from l4d2_converter.sound_prefetch import event_waves, extend_sound_list


class SoundPrefetchTests(unittest.TestCase):
    def test_nested_waves_and_control_prefixes(self):
        source = b'''// "NotAnEvent" { "wave" "bad.wav" }
        "Event.Intro" { "wave" "@#music\\intro.wav" }
        "Event.Tank" { "rndwave" { "wave" "music/tank1.wav" "wave" "*music/tank2.wav" } }
        '''
        result = event_waves(source)
        self.assertEqual(result['event.intro'], {'sound/music/intro.wav'})
        self.assertEqual(result['event.tank'], {'sound/music/tank1.wav', 'sound/music/tank2.wav'})
        self.assertNotIn('notanevent', result)

    def test_preserves_entries_and_avoids_physical_name_duplicates(self):
        before = b'"maps\\c8m1_apartment.bsp"\r\n"sound\\music\\test.360.wav"\r\n'
        after, added = extend_sound_list(before, ['sound/music/test.wav', 'sound/music/new.wav'])
        self.assertTrue(after.startswith(before))
        self.assertEqual(added, ['sound/music/new.wav'])
        self.assertEqual(extend_sound_list(after, added), (after, []))

    def test_rejects_non_audio_and_traversal(self):
        for name in ['sound/../escape.wav', 'materials/test.vtf']:
            with self.assertRaises(ValueError):
                extend_sound_list(b'', [name])


if __name__ == '__main__':
    unittest.main()
