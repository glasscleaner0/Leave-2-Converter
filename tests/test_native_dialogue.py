import struct
import tempfile
import unittest
from pathlib import Path
from l4d2_converter.archive import aligned_zip
from l4d2_converter.native_dialogue import startup_dialogue


def scene(crcs):
    start = 20 + len(crcs) * 16
    return (b'FISV' + struct.pack('>4I', 3, len(crcs), 0, 20)
            + b''.join(struct.pack('>4I', crc, start, 4, start + 4) for crc in crcs)
            + bytes(12))


class NativeDialogueTests(unittest.TestCase):
    def archive(self, folder, name, crcs):
        members = {
            'scenes/scenes.360.image': scene(crcs),
            'scripts/talker/terror_player.txt': b'#include "talker/biker.txt"\n',
            'scripts/talker/biker.txt': b'Response Test { scene "scenes/biker/test.vcd" }',
            'scripts/game_sounds_manifest.txt': b'"game_sounds_manifest" { "precache_file" "scripts/game_sounds_biker.txt" }',
            'scripts/game_sounds_biker.txt': b'"Player.Test" { "wave" "player/survivor/voice/biker/test.wav" }',
            'sound/player/survivor/voice/biker/test.360.wav': b'native audio',
        }
        path = Path(folder)/name
        path.write_bytes(aligned_zip(members))
        return path, members

    def test_complete_native_cache_and_rule_closure(self):
        with tempfile.TemporaryDirectory() as folder:
            base, _ = self.archive(folder, 'base.zip', [1])
            dlc, original = self.archive(folder, 'dlc.zip', [1, 2])
            members, report = startup_dialogue([base, dlc])
            self.assertEqual(members['scenes/scenes.360.image'], original['scenes/scenes.360.image'])
            self.assertEqual(report['response_rule_files'], 2)
            self.assertEqual(report['declared_l4d1_voice_waves'], 1)
            self.assertEqual(report['missing_declared_l4d1_voice_waves'], [])
            self.assertFalse(any(n.startswith('sound/') for n in members))

    def test_rejects_scene_loss(self):
        with tempfile.TemporaryDirectory() as folder:
            base, _ = self.archive(folder, 'base.zip', [1, 2])
            dlc, _ = self.archive(folder, 'dlc.zip', [2, 3])
            with self.assertRaisesRegex(ValueError, 'omits earlier scenes'):
                startup_dialogue([base, dlc])

    def test_missing_rules_fail_instead_of_shipping_partial_registration(self):
        with tempfile.TemporaryDirectory() as folder:
            path, members = self.archive(folder, 'base.zip', [1])
            del members['scripts/talker/biker.txt']
            path.write_bytes(aligned_zip(members))
            with self.assertRaisesRegex(ValueError, 'Missing response-rule include'):
                startup_dialogue([path])


if __name__ == '__main__':
    unittest.main()
