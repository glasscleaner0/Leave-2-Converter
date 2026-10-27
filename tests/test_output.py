import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from l4d2_converter.output import prepare_output


def options(root, **changes):
    values = {'output':str(root/'build'),'input':str(root/'input.vpk'),'sdk_bin':str(root/'sdk'),
              'xbox_game':str(root/'xbox'),'runtime_bin':'','pc_game':'','xbox_assets':'','overwrite':False}
    values.update(changes)
    return SimpleNamespace(**values)


def prior(folder, status='failed'):
    folder.mkdir()
    (folder/'report.json').write_text(json.dumps({'version':'0.2.0','options':{'output':str(folder)},
        'status':status,'jobs':[],'failures':[]}))
    (folder/'extra-user-file.txt').write_text('keep this')
    (folder/'Install').mkdir();(folder/'Install/old.zip').write_bytes(b'old output')


class OutputReuse(unittest.TestCase):
    def test_empty_output_requires_no_override(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);out,backup=prepare_output(options(root))
            self.assertTrue(out.is_dir());self.assertIsNone(backup)

    def test_nonempty_output_requires_explicit_override(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);prior(root/'build')
            with self.assertRaisesRegex(ValueError,'Enable Overwrite'):
                prepare_output(options(root))
            self.assertTrue((root/'build/Install/old.zip').is_file())

    def test_override_preserves_entire_previous_build_and_extras(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);prior(root/'build')
            original={p.relative_to(root/'build'):p.read_bytes() for p in (root/'build').rglob('*') if p.is_file()}
            out,backup=prepare_output(options(root,overwrite=True))
            self.assertEqual(out, (root/'build').resolve())
            self.assertEqual(backup.parent,out.parent)
            self.assertFalse(list(out.iterdir()))
            self.assertEqual({p.relative_to(backup):p.read_bytes() for p in backup.rglob('*') if p.is_file()},original)

    def test_override_refuses_unknown_folder_without_moving_it(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'build').mkdir();(root/'build/user.txt').write_text('keep')
            with self.assertRaisesRegex(ValueError,'original report'):
                prepare_output(options(root,overwrite=True))
            self.assertEqual((root/'build/user.txt').read_text(),'keep')

    def test_running_build_cannot_be_overwritten(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);prior(root/'build','running')
            with self.assertRaises(ValueError):prepare_output(options(root,overwrite=True))
            self.assertTrue((root/'build/Install/old.zip').is_file())

    def test_inputs_and_references_cannot_be_inside_or_contain_output(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            for field in ('input','sdk_bin','xbox_game','runtime_bin','pc_game','xbox_assets'):
                for target in (root/'build',root/'build/source',root):
                    with self.subTest(field=field,target=target),self.assertRaisesRegex(ValueError,'separate'):
                        prepare_output(options(root,overwrite=True,**{field:str(target)}))
            self.assertFalse((root/'build').exists())

    def test_copied_report_does_not_authorize_a_different_folder(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);prior(root/'build')
            p=root/'build/report.json';r=json.loads(p.read_text());r['options']['output']=str(root/'other');p.write_text(json.dumps(r))
            with self.assertRaises(ValueError):prepare_output(options(root,overwrite=True))
            self.assertTrue((root/'build/extra-user-file.txt').is_file())


if __name__=='__main__':unittest.main()
