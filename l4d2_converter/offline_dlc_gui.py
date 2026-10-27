"""Dedicated native Xbox DLC and optional survivor-support page."""
from pathlib import Path
import json,os,queue,threading
import tkinter as tk
from tkinter import ttk,filedialog,messagebox

class OfflineDlcPage:
    def __init__(self,parent,home,can_start=lambda:True):
        self.home=Path(home);self.parent=parent;self.can_start=can_start;self.running=False
        self.events=queue.Queue();self.stop=threading.Event();self.sources=[]
        try:saved=json.loads((self.home/'offline-dlc-settings.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):saved={}
        try:patch_settings=json.loads((self.home/'loader-patch-settings.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):patch_settings={}
        self.sources=list(saved.get('sources',[]))
        frame=ttk.Frame(parent,padding=18);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Offline DLC',font=('Segoe UI',20,'bold')).pack(anchor='w')
        ttk.Label(frame,text='Use your Xbox DLC packages with Leave 2 Loader. No PC installation or MakeGameData is required.',wraplength=780).pack(anchor='w',pady=(6,12))
        self.controls=[]
        def field(label,value,browse):
            ttk.Label(frame,text=label).pack(anchor='w')
            row=ttk.Frame(frame);row.pack(fill='x',pady=(4,10));var=tk.StringVar(value=value)
            entry=ttk.Entry(row,textvariable=var);entry.pack(side='left',fill='x',expand=True)
            button=ttk.Button(row,text='Browse…',command=lambda:browse(var));button.pack(side='left',padx=(8,0))
            self.controls.extend([entry,button]);return var
        self.game=field('Patched Xbox game folder',saved.get('game',patch_settings.get('game','')),lambda v:self.folder(v,'Choose the Leave 2 Loader game'))
        self.output=field('Build output folder (must be new)',saved.get('output',''),self.output_folder)
        self.pc_previews=tk.BooleanVar(value=saved.get('pc_previews',True))
        preview_check=ttk.Checkbutton(frame,text='Recover missing chapter previews from PC (uses saved PC and SDK locations from the Converter page)',variable=self.pc_previews)
        preview_check.pack(anchor='w',pady=(0,8));self.controls.append(preview_check)
        ttk.Label(frame,text='DLC packages or extracted DLC folders:').pack(anchor='w')
        self.list=tk.Listbox(frame,height=4,exportselection=False);self.list.pack(fill='x',pady=(4,6));self.controls.append(self.list)
        row=ttk.Frame(frame);row.pack(fill='x')
        for text,command in [('Add packages…',self.add_packages),('Add extracted folder…',self.add_folder),('Remove selected',self.remove)]:
            button=ttk.Button(row,text=text,command=command);button.pack(side='left',padx=(0,8));self.controls.append(button)
        ttk.Label(frame,text='Builds native campaigns plus startup dialogue registration. Include The Passing and The Sacrifice for their shared voice files; add Cold Stream when importing it. Use Install prepared build to assign the startup archive safely. Disable matching PC campaign/runtime addons before installation.',wraplength=780).pack(anchor='w',pady=(10,8))
        row=ttk.Frame(frame);row.pack(fill='x')
        for text,action in [('Build offline DLC','build'),('Install prepared build','install')]:
            button=ttk.Button(row,text=text,command=lambda a=action:self.start(a));button.pack(side='left',padx=(0,8));self.controls.append(button)
        section=ttk.LabelFrame(frame,text='L4D1 survivor support only',padding=10);section.pack(fill='x',pady=(18,8))
        ttk.Label(section,text='Bodies, materials and arms for Bill, Zoey, Louis and Francis. Full DLC builds also prepare the separate startup voice registration. This survivor-only import does not include dialogue support.',wraplength=750).pack(anchor='w')
        row=ttk.Frame(section);row.pack(fill='x',pady=(8,6))
        self.survivor_source=tk.StringVar(value=saved.get('survivor_source',patch_settings.get('survivor_source','')))
        entry=ttk.Entry(row,textvariable=self.survivor_source);entry.pack(side='left',fill='x',expand=True)
        button=ttk.Button(row,text='Browse…',command=self.browse_survivor);button.pack(side='left',padx=(8,0));self.controls.extend([entry,button])
        button=ttk.Button(section,text='Install survivor support from The Sacrifice DLC',command=lambda:self.start('survivors'));button.pack(anchor='w');self.controls.append(button)
        self.status=tk.StringVar(value='Choose the patched game and your DLC sources.')
        ttk.Label(frame,textvariable=self.status,wraplength=780).pack(anchor='w',pady=(8,4))
        self.bar=ttk.Progressbar(frame,mode='indeterminate');self.bar.pack(fill='x')
        self.log=tk.Text(frame,height=6,wrap='word',state='disabled');self.log.pack(fill='both',expand=True,pady=(8,0))
        self.cancel=ttk.Button(frame,text='Cancel build',command=self.stop.set,state='disabled');self.cancel.pack(anchor='w',pady=(6,0))
        self.refresh();parent.after(100,self.drain)
    def folder(self,var,title):
        value=filedialog.askdirectory(title=title)
        if value:var.set(value)
    def output_folder(self,var):
        value=filedialog.asksaveasfilename(title='Name a new offline DLC build folder',initialfile='Offline-DLC-Build',filetypes=[('Build folder name','*')])
        if value:var.set(value)
    def refresh(self):
        self.list.delete(0,'end')
        for source in self.sources:self.list.insert('end',source)
    def add_packages(self):
        for p in filedialog.askopenfilenames(title='Choose Xbox DLC packages (all files)',filetypes=[('Xbox DLC packages','*')]):
            if p not in self.sources:self.sources.append(p)
        self.refresh()
    def add_folder(self):
        p=filedialog.askdirectory(title='Choose a folder containing extracted left4dead2_dlc folders')
        if p and p not in self.sources:self.sources.append(p);self.refresh()
    def remove(self):
        for i in reversed(self.list.curselection()):del self.sources[i]
        self.refresh()
    def browse_survivor(self):
        p=filedialog.askopenfilename(title='Choose The Sacrifice Xbox DLC package or extracted dlc.360.zip',filetypes=[('Xbox DLC / ZIP','*')])
        if p:self.survivor_source.set(p)
    def say(self,text):
        self.status.set(text);self.log.configure(state='normal');self.log.insert('end',text+'\n');self.log.see('end');self.log.configure(state='disabled')
    def start(self,action):
        if self.running:return
        if not self.can_start():messagebox.showinfo('Operation running','Wait for the current converter or patch operation to finish.');return
        game=self.game.get().strip();output=self.output.get().strip();source=self.survivor_source.get().strip();sources=list(self.sources)
        if not game:messagebox.showinfo('Choose a game','Choose the extracted game patched with Leave 2 Loader.');return
        if action in ('build','install') and not output:messagebox.showinfo('Choose output','Choose the build output folder.');return
        if action=='build' and not sources:messagebox.showinfo('Choose DLC','Add your Xbox DLC packages or an extracted DLC folder.');return
        if action=='survivors' and not source:messagebox.showinfo('Choose The Sacrifice','Choose The Sacrifice DLC package or its extracted dlc.360.zip.');return
        if action in ('install','survivors') and not messagebox.askyesno('Game backup','Have you backed up your game? This installs a new addon and registers it before your replacement addons. Existing addon choices are kept.'):
            return
        saved={'game':game,'output':output,'sources':sources,'survivor_source':source,'pc_previews':self.pc_previews.get()}
        pc_preview_options=None
        if action=='build' and self.pc_previews.get():
            try:conversion_settings=json.loads((self.home/'settings.json').read_text(encoding='utf-8'))
            except (OSError,ValueError):conversion_settings={}
            if all(conversion_settings.get(k) for k in ('pc_game','sdk_bin')):
                pc_preview_options={k:conversion_settings.get(k,'') for k in ('pc_game','sdk_bin','runtime_bin')}
            else:self.say('PC preview recovery not configured; missing thumbnails will use campaign images.')
        try:(self.home/'offline-dlc-settings.json').write_text(json.dumps(saved,indent=2),encoding='utf-8')
        except OSError:pass
        self.running=True;self.stop.clear();self.bar.start()
        for w in self.controls:w.configure(state='disabled')
        self.cancel.configure(state='normal' if action=='build' else 'disabled')
        self.say('Preparing native Xbox DLC…')
        def worker():
            try:
                from .offline_dlc import build_offline_dlc,install_prepared_dlc
                progress=lambda s:self.events.put(('log',s))
                if action=='build':result=build_offline_dlc(game,sources,output,self.home/'tools/x360-convert/bin/x360-convert.exe',progress,self.stop,pc_preview_options=pc_preview_options)
                elif action=='install':result=install_prepared_dlc(game,output,progress)
                else:
                    from .survivor_support import install_support
                    result=install_support(game,source,self.home/'tools/x360-convert/bin/x360-convert.exe',self.home/'work/native-survivors',progress)
                self.events.put(('done',(action,result)))
            except Exception as e:self.events.put(('error',str(e)))
        threading.Thread(target=worker,daemon=True).start()
    def drain(self):
        while True:
            try:kind,value=self.events.get_nowait()
            except queue.Empty:break
            if kind=='log':self.say(value);continue
            self.running=False;self.bar.stop();self.cancel.configure(state='disabled')
            for w in self.controls:w.configure(state='normal')
            if kind=='error':self.say('Stopped: '+value);messagebox.showerror('Offline DLC',value);continue
            action,result=value
            if action=='build':
                self.say('Build ready. '+str(len(result['campaigns']))+' native campaigns prepared.')
                messagebox.showinfo('Offline DLC build ready','The native addons are ready in the output folder, including required L4D1 crew support when applicable. Close Xenia and use Install prepared build when ready.\n\nDisable matching PC campaign/runtime addons first. Console validation is still required.')
            else:
                self.say('Installed: '+result['folder'])
                messagebox.showinfo('Native support installed','Restart the game to load the native addons. Required crew support is enabled for offline L4D1 campaigns; other addon choices were preserved. Test on the console before relying on this beta feature.')
        self.parent.after(100,self.drain)
