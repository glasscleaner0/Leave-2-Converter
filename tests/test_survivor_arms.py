import unittest
from l4d2_converter.survivor_arms import merge_arm_bindings
from l4d2_converter.keyvalues import parse

class SurvivorArms(unittest.TestCase):
    def test_merge_only_missing_survivors_preserves_weapon_settings(self):
        base=b'WeaponData { "clip_size" "17" // retain balance\n CharacterViewmodelAddon { Coach "models/my_coach.mdl" Manager "models/my_louis.mdl" } }'
        donor=b'WeaponData { clip_size 99 CharacterViewmodelAddon { Manager "models/weapons/arms/v_arms_louis.mdl" Biker "models/weapons/arms/v_arms_francis.mdl" } }'
        result,added=merge_arm_bindings(base,donor)
        self.assertIn(b'"clip_size" "17" // retain balance',result)
        self.assertIn(b'Manager "models/my_louis.mdl"',result)
        self.assertEqual([e['character'] for e in added],['Biker']);parse(result.decode())
        self.assertEqual(merge_arm_bindings(result,donor),(result,[]))
    def test_already_correct_magnum_kept_byte_exact(self):
        source=b'WeaponData { CharacterViewmodelAddon { NamVet "models/weapons/arms/v_arms_bill.mdl" } }'
        self.assertEqual(merge_arm_bindings(source,source),(source,[]))
    def test_can_add_mapping_block_when_absent(self):
        source=b'WeaponData { printname test }';donor=b'WeaponData { CharacterViewmodelAddon { TeenGirl "models/weapons/arms/v_arms_zoey.mdl" } }'
        result,added=merge_arm_bindings(source,donor);self.assertEqual(len(added),1);parse(result.decode())

if __name__=='__main__':unittest.main()
