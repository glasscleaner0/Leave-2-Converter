import unittest,tempfile
from pathlib import Path
from types import SimpleNamespace
from l4d2_converter.dependencies import discover
from l4d2_converter.scripts import literal_script_includes,transform
class ScriptIncludes(unittest.TestCase):
 def test_lexer_excludes_comments_examples_and_dynamic_calls(self):
  data=b'// IncludeScript("no")\n/* IncludeScript("no2") */\nprint("IncludeScript(\\"no3\\")"); IncludeScript("shared",this); IncludeScript("x"+suffix);'
  self.assertEqual(literal_script_includes(data),['shared'])
 def test_recursive_encrypted_dependencies_and_missing(self):
  content={'scripts/vscripts/shared.nuc':transform(b'IncludeScript("leaf");',decrypt=False),'scripts/vscripts/leaf.nut':b'IncludeScript("shared"); IncludeScript("absent");'}
  refs=SimpleNamespace(xbox={},supplemental_index={},supplemental={},pc={},dependency_index={},pc_read=lambda n:content.get(n))
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'scripts/vscripts/root.nut';p.parent.mkdir(parents=True);p.write_bytes(b'IncludeScript("shared");')
   result=discover(Path(tmp),refs)
   self.assertEqual(len(result['added']),2)
   self.assertEqual(result['missing'],[{'path':'scripts/vscripts/absent.nut','owner':'scripts/vscripts/leaf.nut'}])
   self.assertEqual(result['invalid'],[])

 def test_padded_script_decoding_still_rejects_interior_nul(self):
  from l4d2_converter.scripts import decode_script
  self.assertEqual(decode_script(transform(b'print(1);\0\0\0',decrypt=False)),b'print(1);')
  with self.assertRaises(ValueError):decode_script(transform(b'print\0(1);',decrypt=False))
