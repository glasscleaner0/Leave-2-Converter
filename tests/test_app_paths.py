from pathlib import Path
from unittest.mock import patch
import unittest,tempfile,json
from l4d2_converter.app_paths import application_home,source_fingerprint

class ApplicationPaths(unittest.TestCase):
    def test_frozen_application_uses_executable_folder_including_spaces(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder)/'Moved Release';home.mkdir()
            with patch('sys.frozen',True,create=True),patch('sys.executable',str(home/'Leave 2 Converter Vanilla.exe')):
                self.assertEqual(application_home(),home.resolve())
                (home/'BUILD-INFO.json').write_text(json.dumps({'converter_source_sha256':'a'*64}))
                self.assertEqual(source_fingerprint(),'a'*64)

    def test_source_application_does_not_depend_on_current_directory(self):
        with patch('sys.frozen',False,create=True):
            self.assertEqual(application_home(),Path(__file__).resolve().parents[1])
            self.assertEqual(len(source_fingerprint()),64)
