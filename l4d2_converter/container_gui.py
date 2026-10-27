"""Integrated notebook page for Xbox container operations."""
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from .containers import ACTIONS, READ_ONLY, ContainerOptions, command, run

class ContainerPage:
    def __init__(self, parent, home, busy_changed=lambda value: None, can_start=lambda: True):
        self.home = Path(home)
        self.settings_path = self.home / 'container-settings.json'
        self.busy_changed = busy_changed
        self.window = parent
        self.can_start = can_start
        self.executable = self.home / 'tools/x360-convert/bin/x360-convert.exe'
        self.running = False
        self.pending_close = False
        self.stop = threading.Event()
        self.events = queue.Queue()
        try:
            settings = json.loads(self.settings_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            settings = {}
        if not isinstance(settings, dict): settings = {}
        if settings.get('action') not in ACTIONS: settings['action'] = 'Extract game files'
        panel = ttk.Frame(self.window, padding=16)
        panel.pack(fill='both', expand=True)
        ttk.Label(panel, text='Xbox game files', font=('Segoe UI', 15)).pack(anchor='w')
        ttk.Label(panel, text='Convert GOD packages, Xbox ISOs and extracted game folders.',
                  wraplength=790).pack(anchor='w', pady=(3,12))
        rows = ttk.Frame(panel)
        rows.pack(fill='x')
        rows.columnconfigure(1, weight=1)
        self.values = {}
        self.widgets = []
        labels = [('action','Operation'),
                  ('source','Input file / extracted folder'), ('output','New output file / folder'),
                  ('title','GOD display title (optional)'), ('title_id','GOD title ID (optional)')]
        defaults = {'action':'Extract game files'}
        self.inputs = {}
        for row, (key, label) in enumerate(labels):
            ttk.Label(rows, text=label).grid(row=row,column=0,sticky='w',padx=(0,10),pady=5)
            value = tk.StringVar(value=settings.get(key,defaults.get(key,'')))
            self.values[key] = value
            if key == 'action':
                entry = ttk.Combobox(rows,textvariable=value,values=list(ACTIONS),state='readonly')
            else:
                entry = ttk.Entry(rows,textvariable=value)
            entry.grid(row=row,column=1,sticky='ew',pady=5)
            self.inputs[key] = entry
            self.widgets.append(entry)
            if key in ('source','output'):
                button=ttk.Button(rows,text='Browse…',command=lambda k=key:self.browse(k))
                button.grid(row=row,column=2,padx=(8,0));self.widgets.append(button)
                if key=='source':
                    self.source_browse = button
                    button=ttk.Button(rows,text='ISO file…',command=lambda:self.browse('source',False))
                    button.grid(row=row,column=3,padx=(5,0));self.widgets.append(button)
                    self.source_alternate = button
        self.hint = tk.StringVar()
        ttk.Label(panel,textvariable=self.hint,wraplength=790).pack(anchor='w',pady=(10,5))
        ttk.Label(panel,text='Use the small GOD package file with its matching .data folder alongside it.\n'
            'Existing outputs are protected. Rebuilt GOD packages require a modified console; hardware compatibility remains unverified.',
            wraplength=790).pack(anchor='w',pady=(0,10))
        controls=ttk.Frame(panel);controls.pack(fill='x')
        self.start=ttk.Button(controls,text='Start',command=self.launch);self.start.pack(side='left')
        self.cancel=ttk.Button(controls,text='Cancel',command=self.stop.set,state='disabled');self.cancel.pack(side='left',padx=8)
        ttk.Button(controls,text='Open output',command=self.open_output).pack(side='right')
        self.status=tk.StringVar(value='Ready')
        ttk.Label(panel,textvariable=self.status).pack(anchor='w',pady=(10,4))
        self.bar=ttk.Progressbar(panel,maximum=100);self.bar.pack(fill='x')
        self.log=tk.Text(panel,height=12,wrap='word',state='disabled');self.log.pack(fill='both',expand=True,pady=(8,0))
        self.values['action'].trace_add('write',lambda *_:self.update_fields())
        self.update_fields()
        self.after_id = self.window.after(100,self.drain)

    def update_fields(self):
        action=ACTIONS.get(self.values['action'].get(),'extract')
        self.inputs['output'].configure(state='disabled' if self.running or action in READ_ONLY else 'normal')
        for key in ('title','title_id'):
            self.inputs[key].configure(state='normal' if not self.running and action=='god' else 'disabled')
        folder_input = action in ('iso','god')
        self.source_browse.configure(text='Game folder…' if folder_input else 'Browse…')
        if folder_input:
            self.source_alternate.configure(text='ISO file…' if action=='god' else 'GOD package…')
            self.source_alternate.grid()
        else:
            self.source_alternate.grid_remove()
        hints={'extract':'Select a GOD package or Xbox ISO. Output is a new extracted-game folder.',
               'iso':'Select a GOD package or extracted folder. Output is a new .iso file.',
               'god':'Select the extracted game folder containing default.xex, or use ISO file…. Output is a new folder containing the GOD package and .data folder. Folder input streams directly to GOD without a temporary ISO.',
               'extract-dlc':'Select a LIVE/PIRS DLC package. Output is a new DLC extraction folder, separate from the base game.',
               'inspect':'Select a GOD package or Xbox ISO. Details appear below; no output is created.',
               'verify-god':'Select a GOD package. Checks block hashes and tables; does not authenticate retail signatures.'}
        self.hint.set(hints[action])

    def browse(self,key,folder=None):
        if self.running:return
        action=ACTIONS.get(self.values['action'].get(),'extract')
        if key=='source' and folder is None:folder = action in ('iso','god')
        if key=='output':
            if action in READ_ONLY:return
            if action=='iso':path=filedialog.asksaveasfilename(parent=self.window,title='New ISO file',defaultextension='.iso',filetypes=[('Xbox ISO','*.iso')])
            else:
                parent=filedialog.askdirectory(parent=self.window,title='Choose the parent folder for the new output')
                if not parent:return
                source=Path(self.values['source'].get()).stem or 'Xbox-game'
                suffix={'god':'GOD','extract':'Extracted','extract-dlc':'DLC'}[action]
                path=str(Path(parent)/(source+'-'+suffix))
        elif folder:
            path=filedialog.askdirectory(parent=self.window,title='Choose the game folder containing default.xex')
        else:
            path=filedialog.askopenfilename(parent=self.window,title='Choose input package or ISO', filetypes=[('All files','*.*')])
        if path:self.values[key].set(path)

    def launch(self):
        if self.running:return
        if not self.can_start():
            messagebox.showinfo('Conversion running','Wait for the current conversion to finish first.',parent=self.window)
            return
        try:
            options=ContainerOptions(executable=str(self.executable),**{k:v.get() for k,v in self.values.items()})
            command(options)
            self.settings_path.write_text(json.dumps({k:v.get() for k,v in self.values.items()},indent=2),encoding='utf-8')
        except Exception as error:
            messagebox.showerror('Check Xbox file settings',str(error),parent=self.window);return
        self.running=True;self.stop.clear();self.busy_changed(True)
        for widget in self.widgets:widget.configure(state='disabled')
        self.start.configure(state='disabled');self.cancel.configure(state='normal')
        self.bar.configure(mode='indeterminate');self.bar.start(10)
        self.log.configure(state='normal');self.log.delete('1.0','end');self.log.configure(state='disabled')
        self.status.set('Starting…')
        def worker():
            try:result=run(options,lambda k,d:self.events.put((k,d)),self.stop)
            except Exception as error:result={'status':'failed','message':str(error)+'\nAn incomplete output may remain; choose a new output before retrying.'}
            self.events.put(('finished',result))
        threading.Thread(target=worker,daemon=True).start()

    def drain(self):
        self.after_id = None
        try:
            while True:
                kind,data=self.events.get_nowait()
                if kind=='progress':
                    self.bar.stop()
                    total=data['total'];done=data['done']
                    if total:
                        self.bar.configure(mode='determinate',value=min(100,100*done/total))
                        self.status.set(f"{data['stage']}: {done/1048576:,.1f} / {total/1048576:,.1f} MiB")
                    else:
                        self.bar.configure(mode='indeterminate');self.bar.start(10);self.status.set(data['stage'])
                elif kind=='finished':
                    self.running=False;self.bar.stop();self.busy_changed(False)
                    for key,widget in self.inputs.items():widget.configure(state='readonly' if key=='action' else 'normal')
                    for widget in self.widgets:
                        if widget not in self.inputs.values():widget.configure(state='normal')
                    self.update_fields();self.start.configure(state='normal');self.cancel.configure(state='disabled')
                    self.status.set(data['message'])
                    if data['status']=='complete':self.bar.configure(mode='determinate',value=100)
                    elif data['status']=='failed':messagebox.showerror('Xbox operation failed',data['message'],parent=self.window)
                else:
                    self.log.configure(state='normal');self.log.insert('end',str(data)+'\n');self.log.see('end');self.log.configure(state='disabled')
        except queue.Empty:pass
        if self.window.winfo_exists():self.after_id = self.window.after(100,self.drain)

    def open_output(self):
        value=self.values['output'].get().strip()
        if not value:return
        path=Path(value)
        if path.is_file():path=path.parent
        if path.is_dir():os.startfile(path)

    def destroy(self):
        if self.after_id is not None:
            self.window.after_cancel(self.after_id)
            self.after_id = None
        # The main application owns the page and its window.

    def close(self):
        if self.running:
            self.stop.set();self.status.set('Cancelling before closing…')
        else:self.destroy()
