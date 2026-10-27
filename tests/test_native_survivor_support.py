from pathlib import Path
import json,struct,tempfile,unittest
from unittest.mock import patch
from l4d2_converter.native_materials import material_text,pool_strings
from l4d2_converter.keyvalues import leaf_pairs
from l4d2_converter.survivor_support import install_support,NAME

def fixture():
    strings=['VertexLitGeneric','$basetexture','models/survivors/body','$translucent']
    pool=b'abcd1PSC'+bytes(4)+struct.pack('>H',0)+bytes(2)+struct.pack('>H',len(strings)+1)
    pool+=b''.join(bytes(3)+s.encode()+b'\0' for s in strings)
    word=lambda n:struct.pack('>HH',n,0)
    data=b'\xaaabcd\0'+word(1)+b'\1'+word(2)+word(3)+b'\x0a'+word(4)+b'\x0b'
    return pool,data

class NativeMaterials(unittest.TestCase):
    def test_decodes_without_pc_assets_or_pool_reference(self):
        pool,data=fixture();text=material_text(data,{b'abcd':pool})
        self.assertIn(b'VertexLitGeneric',text)
        self.assertEqual(dict(leaf_pairs(text)),{'$basetexture':'models/survivors/body','$translucent':'1'})
        self.assertEqual(material_text(text,{}),text)
    def test_missing_pool_and_bad_indices_rejected(self):
        pool,data=fixture()
        with self.assertRaisesRegex(ValueError,'matching string pool'):material_text(data,{})
        bad=bytearray(data);struct.pack_into('>H',bad,6,999)
        with self.assertRaisesRegex(ValueError,'index outside'):material_text(bad,{b'abcd':pool})
    def test_truncated_pools_and_values_rejected(self):
        pool,data=fixture()
        with self.assertRaises(ValueError):pool_strings(pool[:-1])
        with self.assertRaises(ValueError):material_text(data[:-1],{b'abcd':pool})

class SupportInstall(unittest.TestCase):
    def test_registers_low_priority_and_preserves_existing_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);game=root/'game';base=game/'left4dead2';(base/'bin').mkdir(parents=True)
            (game/'default.xex').write_bytes(b'game');(base/'bin/Leave2loader_version.txt').write_text('version 1')
            state=base/'addonlist.txt';original=b'"AddonList" { "My Rochelle" "0" }';state.write_bytes(original)
            staged=root/'staged';staged.mkdir();(staged/'zip0.360.zip').write_bytes(b'support')
            (staged/'leave2-survivors.json').write_text(json.dumps({'assets':[{'path':'a'}]}))
            with patch('l4d2_converter.survivor_support.emulator_running',return_value=False),patch('l4d2_converter.survivor_support.prepare_support',return_value=staged):
                result=install_support(game,'input','exe',root/'work')
                self.assertEqual(result['status'],'survivors-installed')
                self.assertTrue((base/'addons'/NAME/'zip0.360.zip').exists())
                after=state.read_text();self.assertLess(after.index(NAME),after.index('My Rochelle'))
                self.assertIn('"My Rochelle" "0"',after)
                self.assertEqual(Path(result['backup']).read_bytes(),original)
                with self.assertRaisesRegex(ValueError,'already exists'):install_support(game,'input','exe',root/'work')
    def test_running_emulator_blocks_before_filesystem_changes(self):
        with patch('l4d2_converter.survivor_support.emulator_running',return_value=True):
            with self.assertRaisesRegex(ValueError,'Close Xenia'):install_support('missing','input','exe','missing')

if __name__=='__main__':unittest.main()
