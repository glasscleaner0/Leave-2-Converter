import struct,unittest
from l4d2_converter.models import rebind_material_names,model_info
from l4d2_converter.formats import pack_source
class MaterialRebind(unittest.TestCase):
 def fixture(self,e):
  b=bytearray(640);b[:4]=b'IDST' if e=='<' else b'TSDI'
  struct.pack_into(e+'2I',b,4,49,12345);struct.pack_into(e+'I',b,76,len(b))
  struct.pack_into(e+'4I',b,204,2,360,1,488)
  for entry,pos,name in [(360,500,b'first\0'),(424,520,b'second\0')]:
   struct.pack_into(e+'I',b,entry,pos-entry);b[pos:pos+len(name)]=name
  struct.pack_into(e+'I',b,488,540);return bytes(b)
 def test_both_endians_keep_model_and_companion_identity(self):
  for e in ('<','>'):
   before=self.fixture(e);after,r=rebind_material_names(pack_source(before),['private/a','private/b'])
   self.assertEqual(model_info(before),model_info(after));self.assertTrue(r['geometry_and_animation_offsets_preserved'])
   for i,name in enumerate((b'private/a',b'private/b')):
    off=360+64*i;pos=off+struct.unpack_from(e+'I',after,off)[0];self.assertEqual(after[pos:after.index(0,pos)],name)
   count,table=struct.unpack_from(e+'2I',after,212);self.assertEqual(count,1);self.assertEqual(after[struct.unpack_from(e+'I',after,table)[0]],0)
 def test_reject_bad_aliases_and_wrong_table_count(self):
  for names in (['one'],['../escape','valid'],['a.vmt','b']):
   with self.subTest(names=names),self.assertRaises(ValueError):rebind_material_names(self.fixture('<'),names)
