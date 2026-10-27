import tempfile,unittest
from pathlib import Path
from l4d2_converter.archive import aligned_zip
from l4d2_converter.modded_reference import overlay_install
class ModdedReferenceTests(unittest.TestCase):
 def test_enabled_addons_loose_maps_priority(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)/'left4dead2';root.mkdir();(root/'gameinfo.txt').write_text('test');(root/'maps').mkdir();(root/'maps/c8m1_apartment.360.bsp').write_bytes(b'map')
   for name in ('first','last','disabled'):
    folder=root/'addons'/name;folder.mkdir(parents=True);(folder/'zip0.360.zip').write_bytes(aligned_zip({'scripts/test.txt':name.encode()}))
   (root/'addonlist.txt').write_text('"AddonList" { "first" "1" "last" "1" "disabled" "0" }')
   index={};report=overlay_install(index,root.parent);reader,name=index['maps/c8m1_apartment.bsp'];self.assertEqual(reader.read(name),b'map');reader,name=index['scripts/test.txt'];self.assertEqual(reader.read(name),b'last');self.assertEqual(report['enabled_addons'],['first','last'])
 def test_invalid_root_and_traversal(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)
   with self.assertRaises(ValueError):overlay_install({},root)
   (root/'gameinfo.txt').write_text('test');(root/'addonlist.txt').write_text('"AddonList" { "../escape" "1" }')
   with self.assertRaises(ValueError):overlay_install({},root)

 def test_native_xtx_install_from_parent_and_content_folder(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)/'left4dead2';root.mkdir();(root/'gameinfo.xtx').write_bytes(b'console game configuration');(root/'maps').mkdir();(root/'maps/native.360.bsp').write_bytes(b'map')
   for selected in (root.parent,root):
    index={};overlay_install(index,selected);reader,name=index['maps/native.bsp'];self.assertEqual(reader.read(name),b'map')

 def test_empty_reference_zip_valid_but_wrong_count_rejected(self):
  import io,zipfile,struct
  from l4d2_converter.archive import XboxZip
  stream=io.BytesIO()
  with zipfile.ZipFile(stream,'w'):pass
  raw=stream.getvalue();self.assertEqual(XboxZip(raw).entries,{})
  bad=bytearray(raw);struct.pack_into('<HH',bad,8,1,1)
  with self.assertRaisesRegex(ValueError,'count differs'):XboxZip(bytes(bad))
