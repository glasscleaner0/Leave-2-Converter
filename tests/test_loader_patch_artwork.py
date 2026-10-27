import unittest
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from l4d2_converter.loader_patch_gui import LoaderPatchPage

class LoaderArtwork(unittest.TestCase):
    def test_heading_and_two_sided_native_patch_button(self):
        root=tk.Tk();root.withdraw()
        try:
            panel=ttk.Frame(root);panel.pack()
            page=LoaderPatchPage(panel,Path(__file__).resolve().parents[1]);root.update_idletasks()
            layout=repr(ttk.Style(root).layout('LoaderPatch.TButton'))
            self.assertIn('LoaderPatch.LeftMedkit',layout);self.assertIn('LoaderPatch.RightMedkit',layout)
            self.assertEqual(page.apply_button.cget('text').strip(),'Patch Me Up!!')
            self.assertLessEqual(max(page.header_image.width(),page.header_image.height()),96)
            self.assertEqual((page.small_image.width(),page.small_image.height()),(16,15))
            self.assertTrue(page.apply_button.instate(['disabled']))
            self.assertLess(page.apply_button.winfo_reqwidth(),250)
        finally:root.destroy()
