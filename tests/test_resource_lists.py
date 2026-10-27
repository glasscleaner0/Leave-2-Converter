import tempfile
import struct
import unittest
from pathlib import Path
from types import SimpleNamespace
from l4d2_converter.resources import resource_lists, per_map_graph
from l4d2_converter.dependencies import discover
from l4d2_converter.archive import aligned_zip, XboxZip
from l4d2_converter.core import Options, package_layout


def bsp(material, entities=b'', embedded=None):
    lumps = {0:entities, 35:struct.pack('<I',0), 40:aligned_zip(embedded or {}), 43:material.encode()+b'\0'}
    data=bytearray(1036);data[:8]=b'VBSP'+struct.pack('<I',20)
    for index,chunk in lumps.items():
        struct.pack_into('<4I',data,8+16*index,len(data),len(chunk),0,0);data.extend(chunk)
    return bytes(data)


def refs(native, definitions):
    return SimpleNamespace(xbox={n:None for n in native}, supplemental_index={}, supplemental={}, pc={},
        pc_read=lambda n:definitions.get(n),xbox_read=lambda n:definitions[n])


class ResourceLists(unittest.TestCase):
    def test_map_closure_shared_assets_cycles_and_native_paths(self):
        edges={'maps/a.bsp':['materials/a.vmt','models/shared.mdl'],
               'maps/b.bsp':['materials/b.vmt','models/shared.mdl'],
               'materials/a.vmt':['materials/a.vtf'], 'materials/b.vmt':['materials/b.vtf'],
               'models/shared.mdl':['models/shared.mdl','materials/shared.vmt','models/shared.vvd']}
        output=resource_lists({'maps/a.360.bsp':b'a','maps/b.360.bsp':b'b'}, {},'per-map',edges=edges)
        a=output['reslists_xbox/a.360.lst'];b=output['reslists_xbox/b.360.lst']
        self.assertIn(b'materials\\a.vtf',a);self.assertNotIn(b'materials\\b.vtf',a)
        self.assertIn(b'materials\\b.vtf',b);self.assertNotIn(b'maps\\a.bsp',b)
        self.assertIn(b'models\\shared.mdl',a);self.assertNotIn(b'.vvd',a)
        self.assertNotIn(b'.360.',a);self.assertEqual(a.count(b'models\\shared.mdl'),1)
        self.assertEqual(output,resource_lists(dict(reversed(list({'maps/a.360.bsp':b'a','maps/b.360.bsp':b'b'}.items()))),{},'per-map',edges=edges))

    def test_discovery_preserves_native_edges_and_per_map_transitive_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'maps').mkdir()
            (root/'maps/a.bsp').write_bytes(bsp('a'))
            (root/'maps/b.bsp').write_bytes(bsp('b'))
            definitions={'materials/a.vmt':b'Patch { include "materials/base.vmt" }',
                         'materials/base.vmt':b'Shader { "$basetexture" "stock/a" }',
                         'materials/b.vmt':b'Shader { "$basetexture" "stock/b" }'}
            reference=refs(set(definitions)|{'materials/stock/a.vtf','materials/stock/b.vtf'},definitions)
            discovery=discover(root,reference)
            self.assertEqual(discovery['reference_edges']['maps/a.bsp'],['materials/a.vmt'])
            maps={'maps/a.360.bsp':b'a','maps/b.360.bsp':b'b'}
            graphs,issues=per_map_graph(maps,root,reference,discovery)
            self.assertFalse(issues)
            a=resource_lists({'maps/a.360.bsp':b'a'},{},'per-map',edges=graphs['maps/a.bsp'])['reslists_xbox/a.360.lst']
            self.assertIn(b'materials\\stock\\a.vtf',a);self.assertNotIn(b'stock\\b',a)
            self.assertFalse((root/'materials').exists())  # Native traversal is read-only.

    def test_embedded_equal_names_stay_map_specific(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'maps').mkdir()
            for map_name,texture in [('a','a'),('b','b')]:
                (root/f'maps/{map_name}.bsp').write_bytes(bsp('same',embedded={'materials/same.vmt':f'Shader {{ "$basetexture" "{texture}" }}'.encode()}))
            maps={f'maps/{n}.360.bsp':n.encode() for n in ('a','b')}
            discovery={'reference_edges':{'maps/a.bsp':['materials/same.vmt'],'maps/b.bsp':['materials/same.vmt'], 'materials/same.vmt':['materials/b.vtf']}}
            graph,issues=per_map_graph(maps,root,refs({'materials/a.vtf','materials/b.vtf'},{}),discovery)
            self.assertFalse(issues)
            self.assertEqual(graph['maps/a.bsp']['materials/same.vmt'],['materials/a.vtf'])
            self.assertEqual(graph['maps/b.bsp']['materials/same.vmt'],['materials/b.vtf'])

    def test_scripts_direct_audio_and_missing_assets_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'maps').mkdir();(root/'scripts/vscripts').mkdir(parents=True)
            (root/'maps/a.bsp').write_bytes(bsp('a',b'{ "vscripts" "probe" "message" "music/own.wav" "material" "4" "texture" "sprites/laserbeam.spr" }'))
            (root/'scripts/vscripts/probe.nut').write_bytes(b'PrecacheModel("models/absent.mdl"); local x="sound/own.wav";')
            graph,issues=per_map_graph({'maps/a.360.bsp':b'a'},root,refs({'sound/music/own.wav','sound/own.wav','materials/sprites/laserbeam.vmt'},{'materials/sprites/laserbeam.vmt':b'Shader {}'}),{'reference_edges':{}})
            self.assertIn('sound/own.wav',graph['maps/a.bsp']['scripts/vscripts/probe.nut'])
            self.assertNotIn('models/absent.mdl',graph['maps/a.bsp']['scripts/vscripts/probe.nut'])
            self.assertTrue(any(r['path']=='models/absent.mdl' for r in issues))
            self.assertIn('sound/music/own.wav',graph['maps/a.bsp']['maps/a.bsp'])
            self.assertNotIn('materials/4.vmt',graph['maps/a.bsp']['maps/a.bsp'])
            self.assertIn('materials/sprites/laserbeam.vmt',graph['maps/a.bsp']['maps/a.bsp'])

    def test_native_model_materials_and_includes(self):
        from test_model_materials import model
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'maps').mkdir()
            (root/'maps/a.bsp').write_bytes(bsp('',b'{ "model" "models/native.mdl" }'))
            definitions={'models/native.mdl':model(),'materials/body.vmt':b'Shader { "$basetexture" "body" }','materials/body_it.vmt':b'Shader { "$basetexture" "body_it" }'}
            native=set(definitions)|{'materials/body.vtf','materials/body_it.vtf'}
            graph,issues=per_map_graph({'maps/a.360.bsp':b'a'},root,refs(native,definitions),{'reference_edges':{}})
            self.assertFalse(issues)
            self.assertEqual(graph['maps/a.bsp']['models/native.mdl'],['materials/body.vmt','materials/body_it.vmt'])
            self.assertNotIn('materials/unused.vmt',graph['maps/a.bsp']['models/native.mdl'])

    def test_default_option_and_archive_roundtrip(self):
        self.assertEqual(Options('i','s','o','x').resource_list_mode,'per-map')
        with self.assertRaisesRegex(ValueError,'dependency graph'):resource_lists({}, {},'per-map')
        lists=resource_lists({'maps/a.360.bsp':b'a'},{},'per-map',edges={})
        packed,loose=package_layout(lists,{'maps/a.360.bsp':b'a'},{})
        archive=XboxZip(aligned_zip(packed))
        self.assertEqual(archive.read('reslists_xbox/a.360.lst'),b'"maps\\a.bsp"\n')
        self.assertIn('maps/a.360.bsp',loose)
