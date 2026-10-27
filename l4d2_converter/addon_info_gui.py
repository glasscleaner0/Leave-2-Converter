"""Main-thread metadata prompt; no conversion work or filesystem writes."""
import tkinter as tk
from tkinter import ttk,messagebox
from .addon_info import FIELDS,LABELS

def edit_addon_info(parent,request,cancel):
    missing=', '.join(LABELS[k].lower() for k in request['missing_fields'])
    if not messagebox.askyesno('Addon information',
        'This addon has missing information or a Workshop ID for its name.\n\n'
        'Needs attention: '+missing+'.\n\nWould you like to enter addon information before continuing?',parent=parent):return None
    dialog=tk.Toplevel(parent);dialog.title('Addon information');dialog.transient(parent);dialog.resizable(False,False)
    frame=ttk.Frame(dialog,padding=18);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='These details will appear in Leave 2 Loader.').grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,12))
    variables={};entries={};result=[None]
    for row,key in enumerate(FIELDS,1):
        ttk.Label(frame,text=LABELS[key]+(' (required)' if key=='addontitle' else ' (optional)')).grid(row=row,column=0,sticky='w',padx=(0,12),pady=6)
        if key=='addondescription':
            style=ttk.Style(parent)
            entry=tk.Text(frame,width=42,height=4,wrap='word',font='TkDefaultFont',
                background=style.lookup('TEntry','fieldbackground') or 'white',foreground=style.lookup('TEntry','foreground') or 'black',
                insertbackground=style.lookup('TEntry','foreground') or 'black')
            entry.insert('1.0',request['fields'].get(key,''))
        else:
            variables[key]=tk.StringVar(value=request['fields'].get(key,''));entry=ttk.Entry(frame,textvariable=variables[key],width=54)
        entry.grid(row=row,column=1,sticky='ew',pady=6);entries[key]=entry
    def accept():
        values={key:var.get().strip() for key,var in variables.items()}
        values['addondescription']=entries['addondescription'].get('1.0','end-1c').strip()
        if not values['addontitle'] or values['addontitle'].isdecimal():
            messagebox.showinfo('Addon name','Enter a descriptive addon name, rather than only a Workshop ID.',parent=dialog);entries['addontitle'].focus_set();return
        for key,value in values.items():
            if len(value)>(4096 if key=='addondescription' else 256) or any(ord(c)<32 and not (key=='addondescription' and c in '\n\t') for c in value):
                messagebox.showinfo('Check information',LABELS[key]+' is too long or contains unsupported control characters.',parent=dialog);return
        result[0]=values;dialog.destroy()
    def cancel_conversion():cancel();dialog.destroy()
    buttons=ttk.Frame(frame);buttons.grid(row=4,column=0,columnspan=2,sticky='e',pady=(16,0))
    ttk.Button(buttons,text='Cancel conversion',command=cancel_conversion).pack(side='left',padx=(0,12))
    ttk.Button(buttons,text='Skip',command=dialog.destroy).pack(side='left',padx=(0,8))
    ttk.Button(buttons,text='Use details',command=accept).pack(side='left')
    dialog.protocol('WM_DELETE_WINDOW',dialog.destroy);dialog.bind('<Return>',lambda event:accept() if event.widget is not entries['addondescription'] else None);dialog.bind('<Control-Return>',lambda _:accept());dialog.bind('<Escape>',lambda _:dialog.destroy())
    dialog.update_idletasks();dialog.geometry('+%d+%d'%(parent.winfo_rootx()+40,parent.winfo_rooty()+80))
    dialog.grab_set();entries['addontitle'].focus_set();entries['addontitle'].selection_range(0,'end');parent.wait_window(dialog)
    return result[0]
