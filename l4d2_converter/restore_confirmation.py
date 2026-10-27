"""Required acknowledgement before deleting installed mods during rollback."""
import tkinter as tk
from tkinter import ttk

def confirm_clean_restore(parent,game):
    dialog=tk.Toplevel(parent);dialog.title('Restore clean game?');dialog.transient(parent);dialog.resizable(False,False)
    frame=ttk.Frame(dialog,padding=20);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Are you sure you want to restore this game?',font=('Segoe UI',12,'bold')).pack(anchor='w')
    ttk.Label(frame,text=str(game),wraplength=590).pack(anchor='w',pady=(8,12))
    ttk.Label(frame,text='This restores the original files from every saved Loader patch layer and permanently deletes the installed addons folder, saved addon choices, extra numbered game ZIPs (including zip5.360.zip), and Loader startup registration.\n\nStock archives and archives restored from the original backup are retained. Verified original-file backups are kept. Converted output folders outside this game are untouched.',wraplength=590).pack(anchor='w')
    acknowledged=tk.BooleanVar(value=False);result=[False]
    row=ttk.Frame(frame);row.pack(fill='x',pady=(18,0))
    button=ttk.Button(row,text='Restore clean game',state='disabled',command=lambda:(result.__setitem__(0,True),dialog.destroy()))
    check=ttk.Checkbutton(frame,text='I understand this will permanently delete all installed converted mods in this game.',variable=acknowledged,
        command=lambda:button.configure(state='normal' if acknowledged.get() else 'disabled'))
    check.pack(before=row,anchor='w',pady=(16,0))
    ttk.Button(row,text='Cancel',command=dialog.destroy).pack(side='right',padx=(8,0));button.pack(side='right')
    dialog.protocol('WM_DELETE_WINDOW',dialog.destroy);dialog.bind('<Escape>',lambda _:dialog.destroy())
    dialog.grab_set();parent.wait_window(dialog)
    return result[0] and acknowledged.get()
