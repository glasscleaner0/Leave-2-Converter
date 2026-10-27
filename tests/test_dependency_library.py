import tempfile
import unittest
import json
from pathlib import Path
from l4d2_converter.library import DependencyLibrary,dependency_location
from l4d2_converter.dependencies import References,discover
from l4d2_converter.archive import aligned_zip
from test_formats import vpk_bytes


class Library(unittest.TestCase):
    def test_vpk_and_extracted_candidates_read_only_and_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'one.vpk').write_bytes(vpk_bytes().replace(b'folder\0',b'models\0'))
            p=root/'extracted/models/asset.txt';p.parent.mkdir(parents=True);p.write_bytes(b'example')
            library=DependencyLibrary(root)
            self.assertEqual(library.read('models/asset.txt'),b'example')
            self.assertEqual(len(library.used),1)
            self.assertEqual(len(library.used[0]['sources']),2)
            self.assertEqual(p.read_bytes(),b'example')
            self.assertIsNone(library.read('models/absent.mdl'))

    def test_conflicting_unreferenced_candidates_do_not_block_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for label,data in (('a',b'a'),('b',b'b')):
                p=root/label/'materials/wall.vtf';p.parent.mkdir(parents=True);p.write_bytes(data)
            library=DependencyLibrary(root)
            with self.assertRaisesRegex(ValueError,'Conflicting dependency candidates'):library.read('materials/wall.vtf')
            self.assertFalse(library.used)

    def test_library_dependencies_are_followed_but_stock_and_input_win(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir()
            (source/'materials').mkdir()
            (source/'materials/main.vmt').write_bytes(b'"Patch" { "include" "materials/helper.vmt" }')
            pool=root/'pool';(pool/'materials').mkdir(parents=True)
            (pool/'materials/helper.vmt').write_bytes(b'"Shader" { "$basetexture" "wall" }')
            (pool/'materials/wall.vtf').write_bytes(b'payload')
            (pool/'materials/main.vmt').write_bytes(b'wrong override')
            xbox=root/'xbox/left4dead2';xbox.mkdir(parents=True)
            (xbox/'zip0.zip').write_bytes(aligned_zip({'materials/stock.vtf':b'stock'}))
            library=DependencyLibrary(pool)
            refs=References(root/'xbox',library=library)
            result=discover(source,refs)
            self.assertFalse(result['missing']);self.assertFalse(result['invalid'])
            self.assertEqual({r['path'] for r in library.used},{'materials/helper.vmt','materials/wall.vtf'})
            self.assertEqual((source/'materials/wall.vtf').read_bytes(),b'payload')
            self.assertIn(b'Patch',(source/'materials/main.vmt').read_bytes())

    def test_converted_builds_exclusions_corrupt_packages_and_cancellation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'materials').mkdir()
            (root/'materials/a.360.vtf').write_bytes(b'bad')
            (root/'broken.vpk').write_bytes(b'bad')
            (root/'output/models').mkdir(parents=True);(root/'output/models/a.mdl').write_bytes(b'private')
            library=DependencyLibrary(root,excluded=[root/'output'])
            self.assertFalse(library.index);self.assertEqual(len(library.warnings),1)
            with self.assertRaises(InterruptedError):DependencyLibrary(root,cancelled=lambda:True)

    def test_same_location_resolves_file_parent_or_extracted_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'addon.vpk';p.touch()
            self.assertEqual(dependency_location(p,same=True),root)
            self.assertEqual(dependency_location(root,same=True),root)
            self.assertEqual(dependency_location(p,folder='custom'),Path('custom'))
            self.assertIsNone(dependency_location(p))

    def test_historical_build_is_excluded_but_unrelated_report_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for label,report in (('build',{'version':'0.2.3','jobs':[],'status':'failed'}),('addon',[])):
                p=root/label;p.mkdir();(p/'report.json').write_text(json.dumps(report))
                (p/'materials').mkdir();(p/'materials/wall.vtf').write_bytes(label.encode())
            library=DependencyLibrary(root)
            self.assertEqual(library.read('materials/wall.vtf'),b'addon')


if __name__=='__main__':unittest.main()
