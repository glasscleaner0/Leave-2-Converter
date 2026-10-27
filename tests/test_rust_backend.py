"""Native process regressions; explicitly supply MAKEGAMEDATA_RS_TEST_EXE."""
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from l4d2_converter.rust_backend import RustBackend, selected_executable

EXE=os.environ.get('MAKEGAMEDATA_RS_TEST_EXE','')

@unittest.skipUnless(EXE,'Set MAKEGAMEDATA_RS_TEST_EXE to run independent backend process tests')
class NativeBackend(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.tools=self.root/'tools';self.tools.mkdir()
        self.exe=self.tools/'makegamedata-rs-test.exe';shutil.copy2(EXE,self.exe)
        self.rows=[]
    def backend(self, settings=None, cancelled=lambda:False):
        if settings is not None:
            (self.tools/'makegamedata-rs.settings.json').write_text(json.dumps(settings),encoding='utf-8')
        return RustBackend(self.exe,self.root/'build/.work',30,self.rows,cancelled)
    def put(self,backend,name,data):
        path=backend.game/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);return path
    def test_explicit_selection_and_sdk_isolation(self):
        self.assertEqual(selected_executable(self.exe),self.exe)
        self.assertIsNone(selected_executable(self.tools))
        self.assertIsNone(selected_executable(self.tools/'makegamedata.exe'))
        backend=self.backend()
        self.assertFalse(backend.capabilities['requires_proprietary_sdk'])
        self.assertEqual(list((self.root/'build').rglob('*.dll')),[])
    def test_failure_is_structured_and_next_job_still_runs(self):
        backend=self.backend();self.put(backend,'materials/bad.raw',b'bad')
        self.assertFalse(backend.run('materials/bad.raw',['materials/bad.360.raw']))
        self.assertFalse(self.rows[-1]['success'])
        self.assertEqual(self.rows[-1]['result']['failed'],1)
        self.assertTrue(self.rows[-1]['result']['files'][0]['diagnostic']['message'])
        data=bytes(range(256))*384;path=self.put(backend,'materials/good.raw',data)
        self.assertEqual(backend.run('materials/good.raw',['materials/good.360.raw']),{'materials/good.360.raw':data})
        self.assertEqual(path.read_bytes(),data)
    def test_unsupported_format_has_exact_diagnostic(self):
        backend=self.backend();self.put(backend,'particles/test.pcf',b'unsupported')
        self.assertFalse(backend.run('particles/test.pcf',['particles/test.360.pcf']))
        self.assertIn('Unsupported input format',self.rows[-1]['error'])
    def test_visual_policy_is_explicit(self):
        with self.assertRaisesRegex(ValueError,'allow-changes'):
            self.backend({'texture_format':'bgra-if-needed'})
    def test_unknown_settings_refused(self):
        with self.assertRaisesRegex(ValueError,'Unknown Rust backend'):
            self.backend({'pretend_success':True})
    def test_unsafe_output_refused(self):
        backend=self.backend();self.put(backend,'lut.raw',bytes(98304))
        self.assertFalse(backend.run('lut.raw',['../escape.raw']))
        self.assertFalse((self.root/'escape.raw').exists())
    def test_binary_change_is_refused(self):
        backend=self.backend();self.put(backend,'lut.raw',bytes(98304))
        with self.exe.open('ab') as stream:stream.write(b'changed')
        self.assertFalse(backend.run('lut.raw',['lut.360.raw']))
        self.assertIn('executable changed',self.rows[-1]['error'])
    def test_cancellation_propagates(self):
        state=[False];backend=self.backend(cancelled=lambda:state[0]);state[0]=True
        self.put(backend,'lut.raw',bytes(98304))
        with self.assertRaises(InterruptedError):backend.run('lut.raw',['lut.360.raw'])
        self.assertEqual(self.rows[-1]['error'],'Cancelled')
    def model(self,big=False):
        data=bytearray(360);data[:4]=b'TSDI' if big else b'IDST'
        struct.pack_into(('>' if big else '<')+'II',data,4,49,123)
        struct.pack_into(('>' if big else '<')+'I',data,76,len(data));return bytes(data)
    def test_mixed_platform_is_diagnosed_before_conversion(self):
        backend=self.backend()
        self.put(backend,'models/infected/common_male01.phy',struct.pack('<4I',16,0,0,123))
        members={'models/infected/common_male01.360.mdl':self.model(True)}
        with self.assertRaisesRegex(ValueError,'mixed_platform'):
            backend.preflight(members,{'reference_edges':{}})
        report=backend.selection_report['result']
        self.assertEqual(len(report['members']),2)
        self.assertTrue(any('unverified_bundle_mixture' in e for e in report['errors']))
    def test_coherent_family_allows_different_phy_checksum(self):
        backend=self.backend();self.put(backend,'models/test.mdl',self.model())
        self.put(backend,'models/test.phy',struct.pack('<4I',16,0,0,456))
        record=backend.preflight({}, {'reference_edges':{'models/test.mdl':['models/test.phy']}})
        self.assertTrue(record['result']['selection_checks_passed'])
        self.assertTrue(record['result']['warnings'])
        self.assertEqual(len(record['result']['members']),2)
    def test_orphan_animation_is_not_guessed_from_filename(self):
        backend=self.backend();self.put(backend,'models/test.ani',bytes(64))
        with self.assertRaisesRegex(ValueError,'no declaring MDL'):
            backend.preflight({}, {})
