"""Notebook page for the private Vanilla Loader patcher preview."""
from pathlib import Path
import json,queue,threading,os,copy,math
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from .loader_patcher import LoaderPatcher

class LoaderPatchPage:
    def __init__(self,parent,home,can_start=lambda:True):
        self.home=Path(home);self.can_start=can_start;self.running=False;self.events=queue.Queue();self.parent=parent
        self.backend=LoaderPatcher(self.home/'tools/loader-patch');self.backup=None
        frame=ttk.Frame(parent,padding=18);frame.pack(fill='both',expand=True)
        artwork=self.home/'assets/loader'
        full=tk.PhotoImage(master=parent,file=str(artwork/'medkit-header.png'))
        scale=max(1,math.ceil(max(full.width(),full.height())/96))
        self.header_image=full.subsample(scale,scale)
        self.small_image=tk.PhotoImage(master=parent,file=str(artwork/'medkit-small.png'))
        heading=ttk.Frame(frame);heading.pack(fill='x',pady=(0,4))
        ttk.Label(heading,image=self.header_image).pack(side='left',padx=(0,14))
        ttk.Label(heading,text='Leave 2 Loader',font=('Segoe UI',20,'bold')).pack(side='left')
        ttk.Label(frame,text='Patch a supported extracted Left 4 Dead 2 game. Existing addons and their saved choices are kept.',wraplength=780).pack(anchor='w',pady=(6,14))
        ttk.Label(frame,text='Choose the game folder containing default.xex:').pack(anchor='w')
        line=ttk.Frame(frame);line.pack(fill='x',pady=6)
        try:saved=json.loads((self.home/'loader-patch-settings.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):saved={}
        self.game=tk.StringVar(value=saved.get('game',''))
        self.entry=ttk.Entry(line,textvariable=self.game);self.entry.pack(side='left',fill='x',expand=True)
        self.browse_button=ttk.Button(line,text='Browse…',command=self.browse);self.browse_button.pack(side='left',padx=(8,0))
        ttk.Label(frame,text='This beta supports the verified .360.zip layout only. It integrates the matching official update and installs Leave 2 Loader. Disable Aurora’s separate L4D2 title update afterward for this copy.',wraplength=780).pack(anchor='w',pady=(12,8))
        ttk.Label(frame,text='Check first, then apply. Exact backups stay inside the game’s .leave2-loader folder. Restore clean game reverses all saved patch layers and permanently removes installed addons, saved choices and extra game ZIPs; acknowledgement is required.',wraplength=780).pack(anchor='w',pady=(0,14))
        row=ttk.Frame(frame);row.pack(fill='x')
        self.check_button=ttk.Button(row,text='Check game',command=lambda:self.start('check'));self.check_button.pack(side='left')
        style=ttk.Style(parent)
        style.element_create('LoaderPatch.LeftMedkit','image',self.small_image)
        style.element_create('LoaderPatch.RightMedkit','image',self.small_image)
        layout=copy.deepcopy(style.layout('TButton'))
        def decorate(nodes):
            for index,(name,options) in enumerate(nodes):
                if name.endswith('.label'):
                    nodes[index:index+1]=[
                        ('LoaderPatch.LeftMedkit',{'side':'left','sticky':''}),
                        ('LoaderPatch.RightMedkit',{'side':'right','sticky':''}),
                        (name,{**options,'sticky':'nswe'})]
                    return True
                if decorate(options.get('children',[])):return True
            return False
        if not decorate(layout):raise ValueError('Button theme has no label element')
        style.layout('LoaderPatch.TButton',layout)
        style.configure('LoaderPatch.TButton',padding=(10,8),font=('Segoe UI',10,'bold'))
        self.apply_button=ttk.Button(row,text='  Patch Me Up!!  ',style='LoaderPatch.TButton',command=lambda:self.start('apply'),state='disabled');self.apply_button.pack(side='left',padx=8)
        self.restore_button=ttk.Button(row,text='Restore clean game…',command=lambda:self.start('restore'));self.restore_button.pack(side='left')
        self.open_button=ttk.Button(row,text='Open backup folder',command=self.open_backup);self.open_button.pack(side='right')
        self.status=tk.StringVar(value='Choose a game folder and select Check game.')
        ttk.Label(frame,textvariable=self.status,wraplength=780).pack(anchor='w',pady=12)
        self.bar=ttk.Progressbar(frame,mode='indeterminate');self.bar.pack(fill='x')
        self.log=tk.Text(frame,height=12,state='disabled',wrap='word');self.log.pack(fill='both',expand=True,pady=(10,0))
        self.game.trace_add('write',lambda *_:self.apply_button.configure(state='disabled'))
        parent.after(100,self.drain)
    def browse(self):
        if self.running:return
        value=filedialog.askdirectory(title='Choose extracted L4D2 game folder')
        if value:self.game.set(value)
    def say(self,text):
        self.status.set(text);self.log.configure(state='normal');self.log.insert('end',text+'\n');self.log.see('end');self.log.configure(state='disabled')
    def start(self,action):
        if self.running:return
        if not self.can_start():messagebox.showinfo('Operation running','Wait for the current conversion or Xbox file operation to finish.');return
        game=self.game.get().strip()
        if not game:messagebox.showinfo('Choose a game','Choose the extracted game folder first.');return
        if action=='restore':
            from .restore_confirmation import confirm_clean_restore
            if not confirm_clean_restore(self.parent,game):return
        if action=='apply' and not messagebox.askyesno('Game backup','Have you made a backup of your game files?\n\nChoose Yes to continue, or No to stop and make a backup first. The patcher also keeps backups of the files it changes.'):
            return
        self.running=True;self.bar.start()
        for w in (self.entry,self.browse_button,self.check_button,self.apply_button,self.restore_button):w.configure(state='disabled')
        self.say({'check':'Checking compatibility…','apply':'Preparing verified backups…','restore':'Checking backup and installed files…'}[action])
        def worker():
            try:
                progress=lambda s:self.events.put(('log',s))
                result=self.backend.inspect(game) if action=='check' else self.backend.apply(game,progress) if action=='apply' else self.backend.restore_clean(game,progress,acknowledge_mod_deletion=True)
                self.events.put(('done',(action,result)))
            except Exception as e:self.events.put(('error',str(e)))
        threading.Thread(target=worker,daemon=True).start()
    def drain(self):
        while True:
            try:kind,value=self.events.get_nowait()
            except queue.Empty:break
            if kind=='log':self.say(value);continue
            self.running=False;self.bar.stop()
            for w in (self.entry,self.browse_button,self.check_button,self.restore_button):w.configure(state='normal')
            if kind=='error':self.say('Stopped: '+value);messagebox.showerror('Loader Patch',value);continue
            action,result=value
            if result.get('backup'):self.backup=Path(result['backup'])
            if result['status']=='ready':
                self.say('Compatible: '+str(len(result['changed_files']))+' files will change; backups will be created.')
                self.apply_button.configure(state='normal')
                for name in result['changed_files']:self.say('  '+name)
                self.status.set('Compatible. Ready to apply the Loader patch.')
            elif result['status']=='already-installed':self.say('This game already matches the Loader patch. No files changed.')
            elif result['status']=='installed':
                self.say('Loader installed. Backups: '+result['backup'])
                messagebox.showinfo('Loader installed','Leave 2 Loader version 1 is installed.\n\nStart this game normally. Disable its separate Aurora title update because the official update is integrated.\n\nNo addons are included. Add converted addons to left4dead2/addons; Loader detects them automatically. Any addons and enabled/disabled choices you already had were left unchanged.')
            elif result['status']=='restored-clean-cleanup-required':
                self.say('Original files restored, but deletion could not finish: '+result['cleanup_pending'])
                messagebox.showwarning('Cleanup incomplete','The game files were restored, but some removed mod data could not be permanently deleted. Close programs using this folder, then remove the reported cleanup folder:\n\n'+result['cleanup_pending'])
            else:self.say('Original files restored; installed addons and extra archives deleted. Backups retained at '+result['backup'])
            try:(self.home/'loader-patch-settings.json').write_text(json.dumps({'game':self.game.get()},indent=2),encoding='utf-8')
            except OSError:pass
        self.parent.after(100,self.drain)
    def open_backup(self):
        p=self.backup or Path(self.game.get())/'.leave2-loader/backups'
        if p.is_dir():os.startfile(p)
