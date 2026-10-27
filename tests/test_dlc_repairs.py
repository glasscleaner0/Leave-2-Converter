import struct,tempfile,unittest
from pathlib import Path
from l4d2_converter.dlc_repairs import ascii_material_paths,repair_melee_placeholders
from l4d2_converter.formats import bsp_lump

def map_bytes(entity,materials):
    data=bytearray(1036);data[:8]=b'VBSP'+struct.pack('<I',20)
    strings=b'';table=b''
    for name in materials:
        table+=struct.pack('<I',len(strings));strings+=name.encode('cp1252')+b'\0'
    for index,payload in ((0,entity),(3,b'012345678901'),(43,strings),(44,table)):
        offset=len(data);data.extend(payload);struct.pack_into('<4I',data,8+16*index,offset,len(payload),0,0)
    return bytes(data)

class DlcRepairTests(unittest.TestCase):
    def test_material_pair_alias_updates_references_and_preserves_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            game=Path(tmp);materials=game/'materials/dons_decals';materials.mkdir(parents=True);(game/'maps').mkdir()
            stem='serviet bug'+chr(233);vtf=materials/(stem+'.vtf');vtf.write_bytes(b'original pixels')
            vmt=materials/(stem+'.vmt');vmt.write_bytes(('"LightmappedGeneric" { "$basetexture" "dons_decals/'+stem+'" }').encode('cp1252'))
            original=map_bytes(b'{ "classname" "worldspawn" }\0',['dons_decals/'+stem,'brick/unchanged'])
            p=game/'maps/test.bsp';p.write_bytes(original);rows=ascii_material_paths(game)
            self.assertEqual(len(rows),2);self.assertFalse(vtf.exists());self.assertFalse(vmt.exists())
            self.assertEqual(list((game/'materials/l2pc').glob('*.vtf'))[0].read_bytes(),b'original pixels')
            newmaterial=list((game/'materials/l2pc').glob('*.vmt'))[0].read_text();self.assertIn('l2pc/material_',newmaterial)
            result=p.read_bytes();self.assertNotIn(stem.encode('cp1252'),bsp_lump(result,43));self.assertIn(b'brick/unchanged',bsp_lump(result,43))
            self.assertEqual(bsp_lump(result,3),bsp_lump(original,3));self.assertEqual(bsp_lump(result,0),bsp_lump(original,0))
            table=bsp_lump(result,44);strings=bsp_lump(result,43)
            for i in range(0,len(table),4):self.assertGreaterEqual(strings.find(b'\0',struct.unpack_from('<I',table,i)[0]),0)
            self.assertFalse(ascii_material_paths(game))

    def test_v21_material_index_directory_layout_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            game=Path(tmp);material=game/'materials/decals';material.mkdir(parents=True);(game/'maps').mkdir()
            stem='accent'+chr(233);(material/(stem+'.vmt')).write_text('"LightmappedGeneric" { "$basetexture" "brick/test" }')
            data=bytearray(map_bytes(b'{ "classname" "worldspawn" }\0',['decals/'+stem]))
            struct.pack_into('<I',data,4,21)
            for i in range(64):
                offset,size,version,flags=struct.unpack_from('<4I',data,8+16*i)
                struct.pack_into('<4I',data,8+16*i,version,offset,size,flags)
            p=game/'maps/test.bsp';p.write_bytes(data);ascii_material_paths(game)
            result=p.read_bytes();self.assertIn(b'l2pc/material_',bsp_lump(result,43))
            self.assertEqual(bsp_lump(result,3),bsp_lump(data,3));self.assertEqual(struct.unpack_from('<I',result,4)[0],21)

    def test_melee_placeholder_is_removed_without_changing_other_weapons(self):
        with tempfile.TemporaryDirectory() as tmp:
            game=Path(tmp);(game/'maps').mkdir()
            entity=b'{ "classname" "weapon_melee_spawn" "melee_weapon" "any" "model" "models/w_models/weapons/w_pistol_1911.mdl" }\n{ "classname" "weapon_pistol_spawn" "model" "models/w_models/weapons/w_pistol_1911.mdl" }\0'
            p=game/'maps/test.bsp';p.write_bytes(map_bytes(entity,[]));rows=repair_melee_placeholders(game)
            self.assertEqual(rows[0]['entities'],1);changed=bsp_lump(p.read_bytes(),0)
            self.assertEqual(changed.count(b'w_pistol_1911'),1);self.assertIn(b'"melee_weapon" "any"',changed)

if __name__=='__main__':unittest.main()
