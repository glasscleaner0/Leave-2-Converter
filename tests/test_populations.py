import struct,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from l4d2_converter.populations import nav_population,stage_populations,population_blocks

def nav(pop='urban_l4d1',places=(),endian='<'):
    data=struct.pack(endian+'4IBH',0xfeedface,16,14,123,1,len(places))
    for place in places:
        b=place.encode()+b'\0';data+=struct.pack(endian+'H',len(b))+b
    return data+b'\0'+pop.encode()+b'\0'

class Populations(unittest.TestCase):
    def test_nav_reads_population_and_places_in_both_endians(self):
        for endian in ('<','>'):
            self.assertEqual(nav_population(nav(places=['hospital'],endian=endian)),{'population':'urban_l4d1','places':['hospital']})
        for data in (b'',b'garbage',nav()[:18]):
            with self.assertRaises(ValueError):nav_population(data)

    def refs(self,pc):
        return SimpleNamespace(pc_read=lambda name:pc.get(name),xbox={'models/infected/native.mdl':True},xbox_read=lambda name:b'Population { default { native 100 } untouched { native 100 } }')

    def test_union_preserves_unrelated_tables_and_stages_only_missing_models(self):
        pc={'scripts/population.txt':b'Population { urban_l4d1 { missing 60 native 40 } urban_l4d1_mob { missing 100 } hospital { nurse 100 } }',
            'models/infected/missing.mdl':b'model1','models/infected/nurse.mdl':b'model2'}
        with tempfile.TemporaryDirectory() as tmp:
            report=stage_populations(self.refs(pc),{'map1':nav(places=['hospital']),'map2':nav()},tmp)
            self.assertEqual(report['staged_models'],['models/infected/missing.mdl','models/infected/nurse.mdl'])
            self.assertEqual(report['native_models'],['models/infected/native.mdl'])
            self.assertIn('urban_l4d1_mob',report['selected_tables'])
            blocks=population_blocks((Path(tmp)/'scripts/population.txt').read_bytes())
            self.assertEqual(set(blocks),{'default','untouched','urban_l4d1','urban_l4d1_mob','hospital'})
            self.assertEqual((Path(tmp)/'models/infected/missing.mdl').read_bytes(),b'model1')

    def test_missing_population_or_model_fails_explicitly(self):
        for pc,reason in [({'scripts/population.txt':b'Population { }'},'definition missing'),
            ({'scripts/population.txt':b'Population { urban_l4d1 { missing 100 } }'},'infected model missing')]:
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(ValueError,reason):stage_populations(self.refs(pc),{'map':nav()},tmp)