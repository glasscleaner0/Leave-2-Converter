import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from l4d2_converter.containers import ContainerOptions, command, parse_line, run

class Containers(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'input.iso';self.source.write_bytes(b'test')
    def options(self,action='Extract game files',output=None,**kw):
        return ContainerOptions(sys.executable,action,str(self.source),str(output or self.root/'new'),**kw)
    def test_existing_output_and_nested_output_are_refused(self):
        with self.assertRaisesRegex(ValueError,'already exists'):command(self.options(output=self.source))
        folder=self.root/'game';folder.mkdir()
        options=ContainerOptions(sys.executable,'Create ISO',str(folder),str(folder/'new.iso'))
        with self.assertRaisesRegex(ValueError,'outside'):command(options)
    def test_folder_requires_supported_operation(self):
        with self.assertRaisesRegex(ValueError,'not a folder'):
            command(ContainerOptions(sys.executable,'Extract game files',str(self.root),'unused'))
    def test_title_arguments_remain_literal_and_title_id_is_validated(self):
        o=self.options('Create GOD',title='A & B "test"',title_id='0x454108D4')
        args=command(o);self.assertEqual(args[-4:],['--title','A & B "test"','--title-id','454108d4'])
        o.title_id='not hex'
        with self.assertRaisesRegex(ValueError,'hexadecimal'):command(o)
    def test_read_only_operation_does_not_pass_output(self):
        args=command(self.options('Inspect game package',output=self.source))
        self.assertEqual(len(args),3)
    def test_progress_parsing_and_invalid_lines(self):
        kind,p=parse_line('stderr','progress\tiso\t50\t100\n');self.assertEqual((kind,p['done'],p['total']),('progress',50,100))
        self.assertEqual(parse_line('stderr','progress\tiso\tbad\t100')[0],'message')
        self.assertEqual(parse_line('stderr','error\tbad input'),('error','bad input'))
    def test_both_streams_are_drained(self):
        code="import sys\nfor i in range(2000):\n print('output'*30);print('detail'*30,file=sys.stderr)"
        events=[]
        with patch('l4d2_converter.containers.command',return_value=[sys.executable,'-u','-c',code]):
            result=run(self.options(),lambda k,d:events.append((k,d)),threading.Event())
        self.assertEqual(result['status'],'complete');self.assertEqual(len(events),4000)
    def test_cli_errors_are_reported(self):
        code="import sys;print('error\\tbad package',file=sys.stderr);sys.exit(1)"
        with patch('l4d2_converter.containers.command',return_value=[sys.executable,'-c',code]):
            with self.assertRaisesRegex(RuntimeError,'bad package'):run(self.options(),lambda *_:None,threading.Event())
    def test_cancel_stops_child(self):
        stop=threading.Event();timer=threading.Timer(.2,stop.set);timer.start()
        try:
            with patch('l4d2_converter.containers.command',return_value=[sys.executable,'-c','import time;time.sleep(30)']):
                result=run(self.options(),lambda *_:None,stop)
            self.assertEqual(result['status'],'cancelled')
        finally:timer.cancel()

class RealContainerRoundTrip(unittest.TestCase):
    @unittest.skipUnless(sys.platform=='win32','bundled executable is Windows-only')
    def test_real_adapter_iso_god_extraction_roundtrip(self):
        exe=Path(__file__).resolve().parents[1]/'tools/x360-convert/bin/x360-convert.exe'
        if not exe.exists():self.skipTest('optional bundled tool is absent')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir();(source/'nested').mkdir()
            (source/'nested/data.bin').write_bytes(bytes(range(256))*1024)
            xex=bytearray(128);xex[:4]=b'XEX2';struct.pack_into('>I',xex,20,1);struct.pack_into('>II',xex,24,0x40006,64)
            struct.pack_into('>IIII',xex,64,0x12345678,1,1,0x454108d4);xex[80:84]=bytes([2,0,1,1]);(source/'default.xex').write_bytes(xex)
            stages=[]
            def event(kind,data):
                if kind=='progress':stages.append(data['stage'])
            def call(action,src,dest='',**kw):
                return run(ContainerOptions(str(exe),action,str(src),str(dest),**kw),event,threading.Event())
            iso=root/'game.iso';self.assertEqual(call('Create ISO',source,iso)['status'],'complete')
            call('Inspect game package',iso)
            god=root/'god';call('Create GOD',iso,god,title='UI integration test')
            package=next(p for p in god.iterdir() if p.is_file());call('Verify GOD',package)
            extracted=root/'extracted';call('Extract game files',package,extracted)
            def tree(p):return {x.relative_to(p):hashlib.sha256(x.read_bytes()).hexdigest() for x in p.rglob('*') if x.is_file()}
            self.assertEqual(tree(source),tree(extracted))
            roundtrip=root/'back.iso';call('Create ISO',package,roundtrip)
            self.assertEqual(iso.read_bytes(),roundtrip.read_bytes())
            direct=root/'direct-god'
            old_scratch=Path(str(direct)+'.building.iso');old_scratch.mkdir()
            sentinel=old_scratch/'sentinel';sentinel.write_text('preserve')
            stages.clear();call('Create GOD',source,direct,title='Folder input')
            self.assertEqual(set(stages),{'god'})
            self.assertEqual(sentinel.read_text(),'preserve')
            call('Verify GOD',next(p for p in direct.iterdir() if p.is_file()))
