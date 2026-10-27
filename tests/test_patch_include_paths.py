import tempfile
import unittest
from pathlib import Path
from l4d2_converter.dependencies import discover


class EmptyReferences:
    xbox = {}
    supplemental_index = {}
    pc = {}
    def pc_read(self, name):
        return None


class PatchIncludePaths(unittest.TestCase):
    def test_game_root_include_and_material_relative_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {
                'materials/main.vmt': b'Patch { include "rdmg/heavy.vmt" }',
                'rdmg/heavy.vmt': b'VertexLitGeneric { "$fallbackmaterial" "fallback" "$basetexture" "blood" }',
                'materials/fallback.vmt': b'UnlitGeneric {}',
                'materials/blood.vtf': b'texture',
            }
            for name, data in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            result = discover(root, EmptyReferences())
            self.assertFalse(result['missing'])
            self.assertFalse(result['invalid'])
            self.assertEqual(result['reference_edges']['materials/main.vmt'], ['rdmg/heavy.vmt'])
            self.assertEqual(result['reference_edges']['rdmg/heavy.vmt'], ['materials/blood.vtf', 'materials/fallback.vmt'])

    def test_missing_include_reports_exact_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'test.vmt').write_bytes(b'Patch { include "rdmg/missing.vmt" }')
            result = discover(root, EmptyReferences())
            self.assertEqual(result['missing'], [{'path': 'rdmg/missing.vmt', 'owner': 'test.vmt'}])
