import struct
import unittest
from l4d2_converter.keyvalues import parse,tokens,KeyValuesSyntaxError
from l4d2_converter.navigation import transcode


def nav_fixture(version,subversion):
    # One valid area, no connections/ladders/places: observed L4D branch layout.
    b=struct.pack('<4IBHB',0xfeedface,version,subversion,123,1,0,1)+b'default\x00'+struct.pack('<HI',0,1)
    b+=struct.pack('<10I',1,0,*([0]*8))
    b+=struct.pack('<4I',0,0,0,0)+struct.pack('<BIH',0,0,0)
    b+=struct.pack('<2I6fI HII',0,0,*([0.0]*6),0,0,0,0)
    return b+struct.pack('<If',0,1000.0)


class SyntaxAndNavigation(unittest.TestCase):
    def test_unclosed_block_locates_opening_brace(self):
        with self.assertRaises(KeyValuesSyntaxError) as hit:parse('"mission"\n{\n "Name" "Test"\n')
        self.assertEqual((hit.exception.line,hit.exception.column),(2,1))
        self.assertIn('closing brace',str(hit.exception))

    def test_string_comment_and_extra_brace_locations(self):
        for src,line,column,message in (('\n "oops',2,2,'string'),('\n/* never closed',2,1,'comment'),('\n}',2,1,'brace')):
            with self.subTest(src=src),self.assertRaises(KeyValuesSyntaxError) as hit:parse(src)
            self.assertEqual((hit.exception.line,hit.exception.column),(line,column))
            self.assertIn(message,str(hit.exception))

    def test_supported_nav_headers_roundtrip_with_links_validated(self):
        for version,subversion in ((16,14),(15,13)):
            src=nav_fixture(version,subversion)
            console,info=transcode(src);back,other=transcode(console)
            self.assertEqual(back,src)
            self.assertEqual((info['version'],info['subversion']),(version,subversion))
            self.assertEqual(info['areas'],1)
            self.assertTrue(info['all_movement_connections_resolve'])
            self.assertEqual(other['endian'],'>')

    def test_unknown_nav_versions_and_damaged_payloads_still_fail(self):
        with self.assertRaisesRegex(ValueError,'Unsupported NAV version 15/14'):transcode(nav_fixture(15,14))
        with self.assertRaises(AssertionError):transcode(nav_fixture(15,13)[:-10])


if __name__=='__main__':unittest.main()
