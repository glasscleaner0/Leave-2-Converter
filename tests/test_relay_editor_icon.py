import unittest
from l4d2_converter.compatibility import remove_missing_relay_editor_icon
class RelayIcon(unittest.TestCase):
 def test_only_missing_nonrendering_icon_is_removed(self):
  src=b'{ "classname" "logic_relay" "model" "editor/new/logic_relay11.vmt" "OnTrigger" "target,Trigger,,0,-1" }'
  out,rows=remove_missing_relay_editor_icon(src,lambda n:False)
  self.assertNotIn(b'"model"',out);self.assertIn(b'"OnTrigger" "target,Trigger,,0,-1"',out);self.assertEqual(len(rows),1)
  self.assertEqual(remove_missing_relay_editor_icon(out,lambda n:False),(out,[]))
  self.assertEqual(remove_missing_relay_editor_icon(src,lambda n:True),(src,[]))
  prop=src.replace(b'logic_relay"',b'prop_dynamic"',1)
  self.assertEqual(remove_missing_relay_editor_icon(prop,lambda n:False),(prop,[]))
