import struct,unittest
from l4d2_converter.dialogue import validate_scene_image,extend_sound_manifest

def fixture(endian):
    data=bytearray(64);data[:4]=b'VSIF' if endian=='<' else b'FISV';struct.pack_into(endian+'4I',data,4,3,1,1,28);struct.pack_into(endian+'I',data,20,24);data[24:26]=b'a\0';struct.pack_into(endian+'4I',data,28,123,48,8,44)
    return bytes(data)
class DialogueTests(unittest.TestCase):
    def test_scene_cache_in_both_endians(self):
        for endian in ['<','>']:
            r=validate_scene_image(fixture(endian));self.assertEqual(r['scenes'],1);self.assertEqual(r['endian'],endian)
    def test_scene_cache_rejects_bad_string_and_payload(self):
        for offset,value in [(20,99),(32,99),(40,99)]:
            bad=bytearray(fixture('>'));struct.pack_into('>I',bad,offset,value)
            with self.assertRaises(ValueError):validate_scene_image(bytes(bad))
    def test_manifest_preserves_entries_and_is_idempotent(self):
        source=b'game_sounds_manifest { precache_file "scripts/a.txt" preload_file "scripts/base.txt" }'
        result,added=extend_sound_manifest(source,['scripts/a.txt','scripts/voice.txt']);self.assertEqual(added,['scripts/voice.txt']);self.assertIn(b'preload_file "scripts/base.txt"',result)
        self.assertEqual(extend_sound_manifest(result,['scripts/voice.txt']),(result,[]))
        with self.assertRaises(ValueError):extend_sound_manifest(source,['../outside.txt'])

class ResponseIncludeTests(unittest.TestCase):
    def test_include_closure_preserves_original_bytes(self):
        from l4d2_converter.dialogue import response_rule_files
        files={'scripts/talker/main.txt':b'#include "talker/actor.txt"\ncriterion IsActor who Actor', 'scripts/talker/actor.txt':b'#include "shared.txt"\nresponse Test { speak X }','scripts/talker/shared.txt':b'criterion Alive alive 1'}
        self.assertEqual(response_rule_files('scripts/talker/main.txt',files.get),files)
    def test_cycle_and_missing_include_rejected(self):
        from l4d2_converter.dialogue import response_rule_files
        files={'scripts/talker/main.txt':b'#include "main.txt"'}
        with self.assertRaisesRegex(ValueError,'cycle'):response_rule_files('scripts/talker/main.txt',files.get)
        with self.assertRaisesRegex(ValueError,'Missing response'):response_rule_files('scripts/talker/absent.txt',files.get)
