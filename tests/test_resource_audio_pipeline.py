from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile,unittest
from l4d2_converter.core import Options,convert

class ResourceAudioPipeline(unittest.TestCase):
    def test_texture_addon_reaches_dependencies_without_campaign_audio_state(self):
        class Backend:
            def __init__(self,sdk,runtime,work,timeout,rows):
                self.game=Path(work)/'game';self.game.mkdir(parents=True);self.hash='test'
            def close(self):pass
        for decoder in ('','ffmpeg.exe'):
            with self.subTest(decoder=decoder),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);source=root/'source';(source/'materials/effects').mkdir(parents=True)
                (source/'materials/effects/flashlight001.vtf').write_bytes(b'texture fixture')
                options=Options(str(source),'sdk',str(root/'output'),'reference',audio_decoder=decoder)
                with patch('l4d2_converter.core.Backend',Backend),patch('l4d2_converter.rust_backend.selected_executable',return_value=None),patch('l4d2_converter.core.References',return_value=SimpleNamespace(modded_report={})),patch('l4d2_converter.core.discover',side_effect=RuntimeError('Reached texture dependency scan')):
                    result=convert(options,progress=lambda _:None)
                self.assertEqual(result['addon_type'],'resource-addon')
                self.assertEqual(result['mpeg_audio_adapters'],[])
                self.assertEqual(result['error'],'Reached texture dependency scan')
