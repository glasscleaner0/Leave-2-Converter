from pathlib import Path
import tempfile,unittest,json
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch
from l4d2_converter.gui_theme import ThemeManager,PALETTES

class Themes(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        self.settings=Path(self.tmp.name)/'appearance.json'
    def test_default_system_uses_windows_mode_without_saving_override(self):
        with patch('l4d2_converter.gui_theme.system_mode',return_value='Dark'):
            theme=ThemeManager(self.root,self.settings)
        self.assertEqual(theme.mode,'System');self.assertEqual(theme.resolved,'Dark');self.assertFalse(self.settings.exists())
    def test_live_palette_updates_text_without_enabling_disabled_controls(self):
        theme=ThemeManager(self.root,self.settings);text=tk.Text(self.root,state='disabled');button=ttk.Button(self.root,state='disabled')
        for mode in ('Dark','Light','Dark'):
            theme.apply(mode)
            self.assertEqual(str(text.cget('background')),PALETTES[mode]['field'])
            self.assertEqual(str(text.cget('state')),'disabled');self.assertTrue(button.instate(['disabled']))
    def test_persisted_choice_and_system_restore(self):
        theme=ThemeManager(self.root,self.settings);self.assertTrue(theme.apply('Dark',persist=True))
        self.assertEqual(json.loads(self.settings.read_text()),{'theme':'Dark'})
        self.assertEqual(ThemeManager(self.root,self.settings).mode,'Dark')
        theme.apply('System',persist=True);self.assertEqual(json.loads(self.settings.read_text()),{'theme':'System'})
    def test_bad_settings_fall_back_to_system(self):
        for data in ('broken','[]','{"theme":"unknown"}'):
            self.settings.write_text(data);self.assertEqual(ThemeManager(self.root,self.settings).mode,'System')
    def test_invalid_choice_is_rejected(self):
        theme=ThemeManager(self.root,self.settings)
        with self.assertRaises(ValueError):theme.apply('unknown',persist=True)
        self.assertFalse(self.settings.exists())
