import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import wave
from l4d2_converter.audio import fallback_xwv


def wav(width=2,rate=44100):
    f=io.BytesIO()
    with wave.open(f,'wb') as w:
        w.setnchannels(1);w.setsampwidth(width);w.setframerate(rate);w.writeframes(bytes(8*width))
    return f.getvalue()


class Audio(unittest.TestCase):
    def test_supported_pcm_never_invokes_an_external_decoder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.wav';source.write_bytes(wav())
            with patch('l4d2_converter.audio.subprocess.run') as run:
                data,info=fallback_xwv(source,root/'scratch')
            run.assert_not_called();self.assertEqual(data[:4],b'XWV ')
            self.assertTrue(info['source_samples_preserved'])

    def test_external_decode_is_explicit_and_original_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.wav';source.write_bytes(wav(width=1,rate=48000))
            decoder=root/'ffmpeg.exe';decoder.write_bytes(b'fixture tool')
            before=source.read_bytes()
            def run(cmd,**kwargs):
                Path(cmd[-1]).write_bytes(wav())
                return SimpleNamespace(returncode=0,stderr=b'')
            with patch('l4d2_converter.audio.subprocess.run',side_effect=run):
                data,info=fallback_xwv(source,root/'scratch',str(decoder))
            self.assertEqual(source.read_bytes(),before)
            self.assertEqual(data[:4],b'XWV ')
            self.assertEqual(info['output_sample_rate'],44100)
            self.assertFalse(info['source_samples_preserved'])

    def test_compressed_audio_loop_metadata_is_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.wav';decoder=root/'ffmpeg.exe';decoder.write_bytes(b'fixture')
            data=bytearray(wav(width=1));smpl=bytearray(36);struct.pack_into('<I',smpl,28,1)
            data.extend(b'smpl'+struct.pack('<I',len(smpl))+smpl);struct.pack_into('<I',data,4,len(data)-8);source.write_bytes(data)
            with patch('l4d2_converter.audio.subprocess.run') as run,self.assertRaisesRegex(ValueError,'loop metadata'):
                fallback_xwv(source,root/'scratch',str(decoder))
            run.assert_not_called()


if __name__=='__main__':unittest.main()
