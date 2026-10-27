import unittest
from l4d2_converter.core import complete_mission_references
class MissionOnlyTests(unittest.TestCase):
 def test_installed_maps_accepted(self):
  self.assertTrue(complete_mission_references([{'declared':['hotel','dlc'],'available':['hotel','dlc']}]))
 def test_absent_empty_or_partial_rejected(self):
  for rows in ([],[{'declared':[],'available':[]}],[{'declared':['missing'],'available':[]}],[{'declared':['hotel','missing'],'available':['hotel']}]):
   self.assertFalse(complete_mission_references(rows))
