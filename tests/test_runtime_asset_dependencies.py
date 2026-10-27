import struct,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from l4d2_converter.models import break_model_references
from l4d2_converter.dependencies import discover

class RuntimeAssetDependencies(unittest.TestCase):
    def test_embedded_break_models_in_both_endians(self):
        for endian,magic in [('<',b'IDST'),('>',b'TSDI')]:
            kv=b'"break" { "model" "props_urban/skylight_gib01" }\0'
            data=bytearray(320)+kv;data[:4]=magic;struct.pack_into(endian+'II',data,312,320,len(kv))
            self.assertEqual(break_model_references(bytes(data)),['models/props_urban/skylight_gib01.mdl'])
            struct.pack_into(endian+'I',data,312,len(data)+4)
            with self.assertRaisesRegex(ValueError,'outside file'):break_model_references(bytes(data))

    def test_character_texture_slots_are_resolved(self):
        keys=['$iris','$gradienttexture','$ambientoccltexture','$corneatexture','$compress','$stretch','$hdrcompressedtexture']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'materials/character.vmt';p.parent.mkdir()
            p.write_text('VertexLitGeneric { '+' '.join(k+' "test/'+str(i)+'"' for i,k in enumerate(keys))+' }')
            files={'materials/test/'+str(i)+'.vtf':b'texture' for i in range(len(keys))}
            refs=SimpleNamespace(xbox={},supplemental_index={},supplemental={},pc=files,pc_read=lambda n:files.get(n))
            result=discover(root,refs)
            self.assertFalse(result['missing']);self.assertFalse(result['invalid'])
            self.assertEqual({e['path'] for e in result['added']},set(files))