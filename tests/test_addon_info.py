from pathlib import Path
import tempfile,unittest
from l4d2_converter.addon_info import prepare_addon_info
from l4d2_converter.loader import addon_metadata,addon_identifier
from l4d2_converter.keyvalues import parse,Token

class AddonInfo(unittest.TestCase):
    def test_complete_metadata_does_not_prompt_or_rewrite(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'addoninfo.txt';original=b'AddonInfo { addontitle Good addondescription Detail addonauthor Person }';p.write_bytes(original)
            result=prepare_addon_info(folder,'123.vpk',lambda _:self.fail('Unexpected prompt'))
            self.assertEqual(result['status'],'unchanged');self.assertEqual(p.read_bytes(),original)

    def test_workshop_id_prompts_with_existing_fields_and_renames_output_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'addoninfo.txt';p.write_bytes(b'AddonInfo { addontitle 12345 addondescription Existing addonauthor Author addoncontent_campaign 1 }')
            def prompt(details):
                self.assertEqual(details['missing_fields'],['addontitle']);self.assertEqual(details['fields']['addontitle'],'')
                self.assertEqual(details['fields']['addondescription'],'Existing')
                return {**details['fields'],'addontitle':'My Campaign'}
            result=prepare_addon_info(folder,'12345.vpk',prompt)
            fields,_=addon_metadata(p.read_bytes(),'fallback')
            self.assertEqual(addon_identifier('12345.vpk',fields),'My Campaign');self.assertEqual(fields['addoncontent_campaign'],'1')
            self.assertEqual(fields['addonauthor'],'Author');self.assertFalse(result['source_modified'])

    def test_missing_author_decline_preserves_original_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'addoninfo.txt';original=b'AddonInfo { addontitle Name addondescription Description }';p.write_bytes(original)
            def prompt(details):
                self.assertEqual(details['missing_fields'],['addonauthor']);self.assertEqual(details['fields']['addontitle'],'Name');return None
            self.assertEqual(prepare_addon_info(folder,'file.vpk',prompt)['status'],'declined');self.assertEqual(p.read_bytes(),original)

    def test_missing_file_allows_optional_blanks_and_quotes_do_not_inject_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            prepare_addon_info(folder,'123.vpk',lambda _:dict(addontitle='A "Named" Addon',addondescription='',addonauthor=''))
            roots=parse((Path(folder)/'addoninfo.txt').read_text());fields={e.key.value:e.value.value for e in roots[0].value if isinstance(e.value,Token)}
            self.assertEqual(fields['addontitle'],"A 'Named' Addon");self.assertEqual(fields['addondescription'],'');self.assertEqual(len(fields),3)

    def test_cancel_during_prompt_writes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            stopped=[False]
            def prompt(_):stopped[0]=True;return {'addontitle':'Name'}
            with self.assertRaises(InterruptedError):prepare_addon_info(folder,'123.vpk',prompt,lambda:stopped[0])
            self.assertFalse((Path(folder)/'addoninfo.txt').exists())

    def test_numeric_or_blank_manual_name_is_refused_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            for title in ('','12345'):
                with self.assertRaisesRegex(ValueError,'descriptive name'):prepare_addon_info(folder,'123.vpk',lambda _,t=title:{'addontitle':t})
            self.assertFalse((Path(folder)/'addoninfo.txt').exists())

    def test_cli_without_callback_never_blocks_or_creates_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(prepare_addon_info(folder,'123.vpk')['status'],'needs-info-no-prompt')
            self.assertFalse((Path(folder)/'addoninfo.txt').exists())
