import struct
import unittest
from l4d2_converter.formats import bsp_lump, bsp_rows
from l4d2_converter.hdr import prepare_hdr_input, retain_hdr


def bsp(endian, lumps):
    out=bytearray(1036)
    out[:4]=b'VBSP' if endian=='<' else b'PSBV'
    struct.pack_into(endian+'I',out,4,20)
    for i,(data,version) in lumps.items():
        off=len(out);out.extend(data)
        struct.pack_into(endian+'4I',out,8+i*16,off,len(data),version,0)
    return bytes(out)


class Hdr(unittest.TestCase):
    def source(self, hdr=False):
        f,l,w,i,a=(58,53,54,51,55) if hdr else (7,8,15,52,56)
        return bsp('<',{f:(b'face',1),l:(b'light',1),w:(b'world',1),
                        i:(struct.pack('<HH',1,0),0),a:(bytes(range(28)),1),10:(bytes(32),1),0:(b'entity',0)})

    def console(self):
        return bsp('>',{7:(b'FACE',1),8:(b'light',1),15:(b'WORLD',1),0:(b'entity',0)})

    def test_standard_lighting_promotes_and_preserves_ambient(self):
        source=self.source();console=self.console();fixed,record=retain_hdr(console,source)
        self.assertEqual(record['mode'],'standard-lighting-to-console-hdr')
        self.assertEqual(bsp_lump(fixed,51),struct.pack('>HH',1,0))
        self.assertEqual(bsp_lump(fixed,55),bytes(range(28)))
        for standard,hdr in [(7,58),(8,53),(15,54)]:
            self.assertEqual(bsp_lump(fixed,hdr),bsp_lump(console,standard))
            self.assertFalse(bsp_lump(fixed,standard))
        self.assertEqual(bsp_lump(fixed,0),bsp_lump(console,0))

    def test_existing_hdr_selected_for_sdk_and_output(self):
        source=self.source(True);prepared=prepare_hdr_input(source)
        for dst,src in [(7,58),(8,53),(15,54),(52,51),(56,55)]:
            self.assertEqual(bsp_lump(prepared,dst),bsp_lump(source,src))
        fixed,record=retain_hdr(self.console(),source)
        self.assertEqual(record['mode'],'retain-source-hdr')

    def test_invalid_ambient_reference_rejected(self):
        source=bytearray(self.source());offset=bsp_rows(source)[52][0]
        struct.pack_into('<HH',source,offset,2,0)
        with self.assertRaisesRegex(ValueError,'absent samples'):
            retain_hdr(self.console(),source)

    def test_mismatched_sdk_lighting_rejected(self):
        console=bytearray(self.console());offset=bsp_rows(console)[8][0];console[offset]=0
        with self.assertRaisesRegex(ValueError,'lightmap data differs'):
            retain_hdr(console,self.source())

    def test_unknown_leaf_layout_rejected(self):
        source=bytearray(self.source());struct.pack_into('<I',source,8+10*16+8,0)
        with self.assertRaisesRegex(ValueError,'leaf layout'):
            retain_hdr(self.console(),source)
