import math,struct,unittest
from l4d2_converter.frame_animation import sorted_rotation,encode_legacy,legacy_rotation,downgrade_frame_rotations

def sorted_pack(q):
    missing=max(range(4),key=lambda i:abs(q[i]));first=(missing+1)%4
    values=[max(0,min(32767,int(q[(first+i)%4]*23168)+16384)) for i in range(3)]
    values[0]|=(first//2)<<15;values[1]|=(first%2)<<15;values[2]|=32768 if q[missing]<0 else 0
    return struct.pack('<3H',*values)

def fixture():
    mdl=bytearray(600);mdl[:4]=b'IDST';struct.pack_into('<II',mdl,4,49,123);struct.pack_into('<I',mdl,76,len(mdl));struct.pack_into('<I',mdl,156,1)
    struct.pack_into('<II',mdl,180,1,400);struct.pack_into('<II',mdl,352,2,520)
    struct.pack_into('<II',mdl,412,64,2);struct.pack_into('<ii',mdl,452,1,0);struct.pack_into('<II',mdl,528,16,56)
    ani=bytearray(56);ani[:4]=b'IDAG';struct.pack_into('<I',ani,4,49);struct.pack_into('<3I',ani,16,0,28,6);ani[40]=128
    ani[44:50]=sorted_pack((0,0,0,1));ani[50:56]=sorted_pack((0,math.sqrt(.5),0,math.sqrt(.5)))
    return bytes(mdl),bytes(ani)

class FrameRotationTests(unittest.TestCase):
    def test_rotation_roundtrip_axes_signs_and_component_orders(self):
        for axis in range(3):
            for angle in [-3.13,-2,-.4,0,.7,2.9,3.14]:
                q=[0.0]*4;q[axis]=math.sin(angle/2);q[3]=math.cos(angle/2)
                for sign in [-1,1]:
                    q1=sorted_rotation(sorted_pack([v*sign for v in q]));q2=legacy_rotation(encode_legacy(q1))
                    self.assertGreater(abs(sum(a*b for a,b in zip(q1,q2))),.9998)
    def test_animation_keeps_offsets_lengths_and_unrelated_bytes(self):
        mdl,ani=fixture();out,report=downgrade_frame_rotations(mdl,ani)
        self.assertEqual(out['mdl'],mdl);self.assertEqual(len(out['ani']),len(ani));self.assertEqual(out['ani'][40],8)
        changed={i for i,(a,b) in enumerate(zip(ani,out['ani'])) if a!=b}
        self.assertLessEqual(changed,{40}|set(range(44,56)));self.assertEqual(report['rotation_samples'],2)
        again,r=downgrade_frame_rotations(out['mdl'],out['ani']);self.assertEqual(again,out);self.assertEqual(r['rotation_samples'],0)
    def test_rejects_truncation_and_missing_animation_container(self):
        mdl,ani=fixture()
        for value in [None,ani[:-1]]:
            with self.assertRaisesRegex(ValueError,'Missing animation|outside declared block'):downgrade_frame_rotations(mdl,value)
    def test_rejects_stride_mismatch(self):
        mdl,ani=fixture();bad=bytearray(ani);struct.pack_into('<I',bad,24,8)
        with self.assertRaisesRegex(ValueError,'stride'):downgrade_frame_rotations(mdl,bytes(bad))
