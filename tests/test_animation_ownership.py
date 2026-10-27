import unittest
from l4d2_converter.models import model_family

class AnimationOwnership(unittest.TestCase):
    def test_dispatcher_does_not_own_same_stem_animation(self):
        files=['models/anim_coach.mdl','models/anim_coach.ani']
        self.assertEqual(model_family(files[0],files,{'animation_file':None}),[files[0]])
    def test_fallback_owns_different_stem_animation(self):
        files=['models/anim_goach.mdl','models/anim_coach.ani','models/anim_goach.ani']
        self.assertEqual(model_family(files[0],files,{'animation_file':'models/anim_coach.ani'}),files[:2])
