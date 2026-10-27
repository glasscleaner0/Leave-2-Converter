import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from l4d2_converter.core import Options, convert_navigation, texture_alias_reason, converted_name
from l4d2_converter.keyvalues import survival_mission, mission_maps, mission_modes, prepare_mission


class Survival(unittest.TestCase):
    def test_texture_alias_keeps_short_paths_and_handles_legacy_limit(self):
        self.assertIsNone(texture_alias_reason('materials/test.vtf',Path('short')))
        self.assertEqual(texture_alias_reason('materials/test.pwl.vtf',Path('short')),'temporary_vtf_input_alias')
        name='materials/test.vtf'
        overhead=len(str(Path('x')/converted_name(name)))-1
        self.assertIsNone(texture_alias_reason(name,Path('x'*(259-overhead))))
        self.assertEqual(texture_alias_reason(name,Path('x'*(260-overhead))),'short_sdk_texture_path')

    def report(self):
        return {'failures': [], 'warnings': []}

    def test_missing_nav_requires_explicit_opt_in(self):
        self.assertFalse(Options('input', 'sdk', 'output', 'xbox').allow_missing_navigation)
        backend = Mock()
        for allow in (False, True):
            report = self.report(); members = {}
            convert_navigation('maps/test.bsp', {}, Path('.'), backend, members, report, allow)
            self.assertEqual(bool(report['failures']), not allow)
            self.assertEqual(bool(report['warnings']), allow)
            if allow:
                self.assertEqual(report['navigation'][0]['status'], 'absent-allowed')
            self.assertEqual(members, {})
        backend.run.assert_not_called()

    def test_opt_in_still_converts_existing_navigation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'maps').mkdir(); (root/'maps/test.nav').write_bytes(b'pc-nav')
            for allow in (False, True):
                report=self.report(); members={}
                backend=Mock(); backend.run.return_value={'maps/test.360.nav':b'console-nav'}
                with patch('l4d2_converter.core.unpack_source',return_value=b'decoded'), \
                     patch('l4d2_converter.navigation.transcode',return_value=(b'pc-nav',{'areas':3})):
                    convert_navigation('maps/test.bsp', {'maps/test.nav':1}, root, backend, members, report, allow)
                backend.run.assert_called_once_with('maps/test.nav',['maps/test.360.nav'])
                self.assertEqual(members['maps/test.360.nav'],b'console-nav')
                self.assertTrue(report['navigation'][0]['roundtrip_exact'])
                self.assertFalse(report['failures'])

    def test_opt_in_does_not_hide_failed_or_damaged_nav(self):
        backend=Mock(); backend.run.return_value={}
        report=self.report()
        convert_navigation('maps/test.bsp',{'maps/test.nav':1},Path('.'),backend,{},report,True)
        self.assertEqual(report['failures'][0]['reason'],'NAV conversion failed')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'maps').mkdir(); (root/'maps/test.nav').write_bytes(b'pc-nav')
            backend.run.return_value={'maps/test.360.nav':b'console-nav'}
            with patch('l4d2_converter.core.unpack_source',return_value=b'decoded'), \
                 patch('l4d2_converter.navigation.transcode',return_value=(b'wrong',{})), \
                 self.assertRaisesRegex(ValueError,'roundtrip'):
                convert_navigation('maps/test.bsp',{'maps/test.nav':1},root,backend,{},self.report(),True)

    def test_survival_metadata_and_mixed_modes_are_preserved(self):
        source=b'"mission" { "Name" "Mixed" "modes" { "coop" { "1" { "Map" "coop1" } } "survival" { "1" { "Map" "survival1" "DisplayName" "Float" } } } }'
        _,data=prepare_mission(source)
        self.assertEqual(mission_modes(data),['coop','survival'])
        self.assertEqual(mission_maps(data),['coop1','survival1'])
        self.assertIn(b'"DisplayName" "Float"',data)

    def test_generated_metadata_safe_and_survival_only(self):
        identifier,data=survival_mission('testsurvival',['tumtara_+&','map2','map2'])
        self.assertEqual(identifier,'testsurvival')
        self.assertEqual(mission_modes(data),['survival'])
        self.assertEqual(mission_maps(data),['tumtara_+&','map2'])
        for names in ([], ['../bad'], ['bad"injection'], ['a//b']):
            with self.subTest(names=names),self.assertRaises(ValueError):survival_mission('test',names)
        for bad in ('bad"id','test_survival','test-survival'):
            with self.subTest(identifier=bad),self.assertRaises(ValueError):survival_mission(bad,['test'])


if __name__ == '__main__':
    unittest.main()
