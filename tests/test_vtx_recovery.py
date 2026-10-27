import struct,unittest
from l4d2_converter.vtx import relayout,finish_console,layout
from l4d2_converter.vtx_recovery import recover_index_tail
from l4d2_converter.formats import pack_source,unpack_source
from test_vtx import fixture


def sample(e):
    d=bytearray(fixture(e));d=d[:134]+bytes(120)+bytes(8)
    for p,v in ((81,60),(98,60),(117,0),(121,0),(24,254)):
        struct.pack_into(e+'I',d,p,v)
    d[125:134]=bytes(9)
    modern,_=relayout(bytes(d),e,(25,27),(33,35))
    return modern


class Recovery(unittest.TestCase):
    def broken(self):
        s=sample('<');d=bytearray(sample('>'))
        replacement=struct.unpack_from('>I',d,24)[0]
        del d[replacement-10:replacement]
        struct.pack_into('>I',d,24,replacement-10)
        return s,d

    def test_restores_source_indices_without_changing_vertices_or_strips(self):
        s,d=self.broken()
        with self.assertRaises(ValueError):layout(d,'>',33,35)
        result,row=recover_index_tail(bytes(d[:36])+pack_source(bytes(d[36:])),s)
        self.assertEqual(row['buffers'][0]['recovered_tail_bytes'],10)
        repaired=result[:36]+unpack_source(result[36:]);layout(repaired,'>',33,35)
        self.assertEqual(repaired[36:85],d[36:85])
        final,_=finish_console(result);layout(final[:36]+unpack_source(final[36:]),'>',25,27)

    def test_rejects_prefix_or_vertex_mismatch(self):
        s,d=self.broken();d[150+16]=99
        with self.assertRaises(ValueError):recover_index_tail(bytes(d),s)
        s,d=self.broken();d[141]=99
        with self.assertRaises(ValueError):recover_index_tail(bytes(d),s)

    def test_rejects_large_loss_and_nonempty_replacement_table(self):
        s,d=self.broken();replacement=struct.unpack_from('>I',d,24)[0]
        del d[replacement-40:replacement];struct.pack_into('>I',d,24,replacement-40)
        with self.assertRaises(ValueError):recover_index_tail(bytes(d),s)
        s,d=self.broken();d[-1]=1
        with self.assertRaises(ValueError):recover_index_tail(bytes(d),s)

if __name__=='__main__':unittest.main()


