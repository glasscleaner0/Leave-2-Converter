"""Bundled application artwork, resolved beside the GUI rather than the cwd."""
from pathlib import Path
import tkinter as tk
import math

def window_icons(window,home):
    source=tk.PhotoImage(master=window,file=str(Path(home)/'assets/app/vanilla.png'))
    icons=[source.subsample(max(1,math.ceil(max(source.width(),source.height())/size))) for size in (128,64,32,16)]
    window.iconphoto(True,*icons)
    return icons # Keep references alive for the lifetime of the window.
