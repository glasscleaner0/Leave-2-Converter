import unittest
from l4d2_converter.scripts import transform,decode_script
class ScriptControls(unittest.TestCase):
 def test_entity_separator_in_quoted_string_preserved(self):
  source=b'local command = "director\x1bRunScriptCode\x1bRun()";\n'
  self.assertEqual(decode_script(transform(source,decrypt=False)),source)
 def test_controls_outside_strings_and_wrong_controls_rejected(self):
  for source in (b'local x = 1;\x1b\n',b'local x = "bad\x01";\n',b'// "\x1b"\nlocal x=1;'):
   with self.assertRaises(ValueError):decode_script(transform(source,decrypt=False))
