import unittest
from l4d2_converter.survivor_requirements import requires_l4d1,require_crew_enabled,CREW

class Requirements(unittest.TestCase):
    def test_only_explicit_mission_survivor_set(self):
        self.assertTrue(requires_l4d1(b'mission { survivor_set 1 }'))
        self.assertFalse(requires_l4d1(b'mission { survivor_set 2 }'))
        self.assertFalse(requires_l4d1(b'mission { description "survivor_set 1" }'))
    def test_required_state_change_is_scoped(self):
        source=('"AddonList" { "'+CREW+'" "0" "Mine" "0" }').encode()
        result=require_crew_enabled(source)
        self.assertIn(('"'+CREW+'" "1"').encode(),result);self.assertIn(b'"Mine" "0"',result)
        self.assertEqual(require_crew_enabled(result),result)

if __name__=='__main__':unittest.main()
