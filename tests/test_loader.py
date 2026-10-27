import hashlib
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from l4d2_converter.loader import addon_metadata, addon_identifier, rgba_vtf, preview_source, build_preview, write_loader_output, preview_identity
from test_loading import texture

class Backend:
    def __init__(self, game, fail=False): self.game=game; self.rows=[]; self.fail=fail
    def run(self, logical, expected):
        self.rows.append({'input':logical})
        return {} if self.fail else {expected[0]:texture(128,128)}

class LoaderOutput(unittest.TestCase):
    def test_l4d1_campaign_marks_required_offline_crew_support(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);game=root/'game';game.mkdir();out=root/'out';out.mkdir()
            mission=b'mission { Name Custom survivor_set 1 modes { coop { 1 { Map test } } } }'
            folder,report=write_loader_output(out,'demo.vpk',game,b'archive',{'missions/demo.txt':mission},Backend(game),progress=lambda _:None)
            self.assertTrue(report['requires_l4d1_survivor_support'])
            self.assertIn(b'"leave2_requires_l4d1_survivors" "1"',(folder/'addoninfo.txt').read_bytes())
            self.assertTrue((folder/'L4D1-SURVIVOR-SUPPORT.txt').is_file())
    def test_sidecar_jpg_then_embedded_vtf_then_embedded_jpg(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);game=root/'game';game.mkdir();source=root/'demo.vpk';source.touch()
            (game/'addonimage.vtf').write_bytes(b'embedded');(root/'demo.jpg').touch();(root/'demo.PNG').touch()
            self.assertEqual(preview_source(source,game)[1],'sidecar.jpg')
            (root/'demo.jpg').unlink()
            self.assertEqual(preview_source(source,game)[1],'embedded.vtf')
            (game/'addonimage.vtf').unlink();(game/'addonimage.jpg').touch()
            self.assertEqual(preview_source(source,game)[1],'embedded.jpg')
            (game/'addonimage.jpg').unlink();self.assertEqual(preview_source(source,game)[1],'sidecar.png')

    def test_sidecar_matching_is_case_insensitive_and_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);game=root/'game';game.mkdir();source=root/'123.VPK';source.touch()
            (game/'addonimage.vtf').touch();(root/'different.jpg').touch()
            self.assertEqual(preview_source(source,game)[1],'embedded.vtf')
            jpg=root/'123.JPG';jpg.touch();self.assertEqual(preview_source(source,game),(jpg,'sidecar.jpg'))
            jpg.unlink();jpeg=root/'123.JPEG';jpeg.touch()
            self.assertEqual(preview_source(source,game),(jpeg,'sidecar.jpeg'))

    def test_rgba_header_and_pixels(self):
        pixels=bytes(range(256))*256;data=rgba_vtf(pixels)
        self.assertEqual(data[:4],b'VTF\0');self.assertEqual(struct.unpack_from('<2H',data,16),(128,128))
        self.assertEqual(data[80:],pixels)
        with self.assertRaises(ValueError):rgba_vtf(b'bad')

    def test_metadata_and_identifiers(self):
        fields,warnings=addon_metadata(b'"AddonInfo" { "addontitle" "Nessie Ammo" }','fallback')
        self.assertFalse(warnings);self.assertEqual(addon_identifier('3036325844.vpk',fields),'Nessie Ammo')
        fields,warnings=addon_metadata(b'"AddonInfo" {','fallback');self.assertTrue(warnings)
        self.assertEqual(fields['addontitle'],'fallback')
        self.assertTrue(addon_identifier('CON.vpk',{}).startswith('Addon_'))

    def test_collision_preserves_existing_staging_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            game=Path(tmp);(game/'addonimage.vtf').write_bytes(b'input')
            logical='materials/__converter_input/loader-preview-'+hashlib.sha256(b'demo').hexdigest()[:16]+'.vtf'
            existing=game/logical;existing.parent.mkdir(parents=True);existing.write_bytes(b'keep')
            result,info,warnings=build_preview(game,Backend(game),'demo')
            self.assertIsNone(result);self.assertEqual(info['status'],'omitted');self.assertTrue(warnings)
            self.assertEqual(existing.read_bytes(),b'keep')

    def test_optional_failure_and_no_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            game=Path(tmp);backend=Backend(game,True)
            self.assertEqual(build_preview(game,backend,'demo')[1]['status'],'none')
            (game/'addonimage.vtf').write_bytes(b'input')
            result,info,warnings=build_preview(game,backend,'demo')
            self.assertIsNone(result);self.assertTrue(warnings);self.assertTrue(backend.rows[0]['optional'])
            self.assertFalse(list(game.rglob('loader-preview-*')))

    def test_complete_folder_preserves_assets_and_separates_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);game=root/'game';game.mkdir();out=root/'out';out.mkdir()
            (game/'addoninfo.txt').write_bytes(b'"AddonInfo" { "addontitle" "Demo" "addonauthor" "Author" }')
            (game/'addonimage.vtf').write_bytes(b'input');archive=b'archive';loose={'maps/demo.360.bsp':b'map','missions/demo.txt':b'mission'}
            folder,report=write_loader_output(out,'demo.vpk',game,archive,loose,Backend(game),progress=lambda _:None)
            self.assertEqual((folder/'zip0.360.zip').read_bytes(),archive)
            for name,data in loose.items():self.assertEqual((folder/name).read_bytes(),data)
            self.assertFalse((out/'Install').exists());self.assertFalse(list(out.rglob('addonlist.txt')))
            cache_name=preview_identity('Demo',texture(128,128))
            self.assertIn(('leave2/addons/'+cache_name).encode(),(folder/'addoninfo.txt').read_bytes())
            with zipfile.ZipFile(folder/'ui/zip0.360.zip') as z:
                self.assertEqual(z.read('materials/vgui/leave2/addons/'+cache_name+'.360.vtf'),texture(128,128))
                self.assertIn(('vgui/leave2/addons/'+cache_name).encode(),z.read('materials/vgui/leave2/addons/'+cache_name+'.vmt'))
            self.assertFalse(report['addonlist_written'])

    def test_generic_titles_with_different_previews_cannot_share_cache_key(self):
        class OtherImage(Backend):
            def run(self,logical,expected):
                result=super().run(logical,expected)
                result[expected[0]]=result[expected[0]][:-1]+b'\x7f'
                return result
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);game=root/'game';game.mkdir()
            (game/'addoninfo.txt').write_bytes(b'"AddonInfo" { "addontitle" "Addon" }')
            (game/'addonimage.vtf').write_bytes(b'input')
            names=[]
            for label,kind in [('a',Backend),('b',OtherImage)]:
                out=root/label;out.mkdir()
                folder,report=write_loader_output(out,'source.vpk',game,b'archive',{},kind(game),progress=lambda _:None)
                names.append(report['preview']['cache_key'])
                self.assertIn(names[-1].encode(),(folder/'addoninfo.txt').read_bytes())
                with zipfile.ZipFile(folder/'ui/zip0.360.zip') as z:
                    key='materials/vgui/'+names[-1]
                    self.assertIn((names[-1]).encode(),z.read(key+'.vmt'))
                    self.assertIn(key+'.360.vtf',z.namelist())
            self.assertNotEqual(names[0],names[1])
            self.assertEqual(preview_identity('Addon',b'image'),preview_identity('ADDON',b'image'))

if __name__=='__main__':unittest.main()
