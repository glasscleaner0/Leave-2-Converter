"""Small Tk interface; conversion logic lives entirely in l4d2_converter.core."""
import json
import os
import sys
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from l4d2_converter import __version__
from l4d2_converter.core import Options, convert
from l4d2_converter.library import dependency_location

from l4d2_converter.app_paths import application_home
HERE = application_home()


class App:
    def __init__(self, window):
        self.window = window
        window.title('Leave 2 Converter Vanilla v0.5 Public Beta')
        window.geometry('850x850')
        from l4d2_converter.gui_theme import ThemeManager,CHOICES
        self.theme_manager=ThemeManager(window,HERE/'appearance.json')
        theme_bar=ttk.Frame(window,padding=(6,2))
        self.theme_label=ttk.Label(theme_bar,text='Theme')
        self.theme_choice=tk.StringVar(value=self.theme_manager.mode)
        self.theme_selector=ttk.Combobox(theme_bar,textvariable=self.theme_choice,values=CHOICES,state='readonly',width=9)
        self.theme_selector.pack(side='right')
        self.theme_label.pack(side='right',padx=(0,8))
        def change_theme(_event=None):
            saved=self.theme_manager.apply(self.theme_choice.get(),persist=True)
            self.theme_label.configure(text='Theme' if saved else 'Theme (not saved)')
            if hasattr(self,'install_help_link'):self.install_help_link.configure(foreground=self.theme_manager.palette['accent'])
        self.theme_selector.bind('<<ComboboxSelected>>',change_theme)
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.running = False
        self.fields = {}
        self.entries = {}
        try:
            settings = json.loads((HERE / 'settings.json').read_text())
        except (OSError, ValueError):
            settings = {}
        self.tabs = ttk.Notebook(window)
        self.tabs.pack(fill='both', expand=True)
        # Share the notebook's tab strip instead of consuming another full row.
        theme_bar.place(in_=self.tabs,relx=1,x=-8,y=2,anchor='ne')
        theme_bar.lift()
        converter_tab=ttk.Frame(self.tabs)
        footer=ttk.Frame(converter_tab,padding=(14,8,14,12))
        footer.pack(side='bottom',fill='x')
        option_area=ttk.Frame(converter_tab)
        option_area.pack(fill='both',expand=True)
        self.option_canvas=tk.Canvas(option_area,highlightthickness=0,borderwidth=0,
                                     background=self.theme_manager.palette['bg'])
        option_scroll=ttk.Scrollbar(option_area,orient='vertical',command=self.option_canvas.yview)
        option_scroll.pack(side='right',fill='y')
        self.option_canvas.pack(side='left',fill='both',expand=True)
        self.option_canvas.configure(yscrollcommand=option_scroll.set)
        panel = ttk.Frame(self.option_canvas, padding=14)
        option_window=self.option_canvas.create_window((0,0),window=panel,anchor='nw')
        panel.bind('<Configure>',lambda _e:self.option_canvas.configure(scrollregion=self.option_canvas.bbox('all')))
        self.option_canvas.bind('<Configure>',lambda e:self.option_canvas.itemconfigure(option_window,width=e.width))
        def scroll_options(event):
            widget=event.widget
            while widget is not None:
                if widget in (panel,self.option_canvas):
                    self.option_canvas.yview_scroll(-int(event.delta/120),'units')
                    return 'break'
                widget=getattr(widget,'master',None)
        window.bind('<MouseWheel>',scroll_options,add='+')
        self.test_tab = ttk.Frame(self.tabs)
        self.tabs.add(converter_tab, text='Converter')
        self.tabs.add(self.test_tab, text='PC to DLC')
        ttk.Label(panel, text='Convert a PC campaign or resource addon with the selected backend.',
                  font=('Segoe UI', 12)).pack(anchor='w', pady=(0, 10))
        rows = ttk.Frame(panel)
        rows.pack(fill='x')
        self.buttons = []
        self.additional_inputs = list(settings.get('additional_inputs', []))
        for index, (key, label) in enumerate((('input', 'Addon VPK / extracted folder'),
                                            ('dependency_folder','Dependency folder (optional)'),
                                            ('sdk_bin', 'MakeGameData SDK bin'),
                                            ('runtime_bin', 'Dino D-Day DLLs (SDK only)'),
                                            ('audio_decoder', 'FFmpeg (audio / PNG previews)'),
                                            ('xbox_game', 'Clean Xbox game reference'),
                                            ('xbox_assets', 'Console DLC assets (optional)'),
                                            ('modded_xbox_game', 'Modded Xbox L4D2 install (optional)'),
                                            ('pc_game', 'PC game installation (optional)'),
                                            ('output', 'Output folder'))):
            ttk.Label(rows, text=label).grid(row=index, column=0, sticky='w', padx=(0, 12), pady=4)
            value = tk.StringVar(value=settings.get(key, ''))
            self.fields[key] = value
            entry=ttk.Entry(rows,textvariable=value)
            entry.grid(row=index,column=1,sticky='ew',pady=4)
            self.entries[key]=entry
            button = ttk.Button(rows, text='Browse…', command=lambda k=key: self.browse(k))
            button.grid(row=index, column=2, padx=(8, 0))
            self.buttons.append(button)
            if False:  # Vanilla has no Rust selector
                def choose_rust():
                    if self.running: return
                    path = filedialog.askopenfilename(title='Choose independent Rust converter',filetypes=[('Rust converter','makegamedata-rs*.exe')])
                    if path: self.fields['sdk_bin'].set(path)
                rust_button = ttk.Button(rows,text='Rust…',command=choose_rust)
                rust_button.grid(row=index,column=3,padx=(5,0))
                self.buttons.append(rust_button)
            if key=='dependency_folder':self.dependency_browse=button
            if key == 'input':
                folder = ttk.Button(rows, text='Folder…', command=lambda: self.browse('input', True))
                folder.grid(row=index, column=3, padx=(5, 0))
                self.buttons.append(folder)
        rows.columnconfigure(1, weight=1)
        self.dependency_manual=self.fields['dependency_folder'].get()
        self.dependency_was_same=False
        self.dependency_same=tk.BooleanVar(value=settings.get('dependencies_same_as_input',False))
        self.dependency_check=ttk.Checkbutton(panel,text='Dependency folder is the same as the addon location',
            variable=self.dependency_same,command=self.update_dependency_folder)
        self.dependency_check.pack(anchor='w',pady=(5,0))
        self.fields['input'].trace_add('write',lambda *_:self.update_dependency_folder())
        self.update_dependency_folder()
        parts = ttk.Frame(panel)
        parts.pack(fill='x',pady=(6,0))
        self.parts_label = tk.StringVar()
        self.update_parts_label()
        ttk.Label(parts,textvariable=self.parts_label).pack(side='left')
        add_parts = ttk.Button(parts,text='Combine VPK Packages…',command=self.browse_parts)
        add_parts.pack(side='right')
        clear_parts = ttk.Button(parts,text='Clear parts',command=self.clear_parts)
        clear_parts.pack(side='right',padx=6)
        self.buttons.extend([add_parts,clear_parts])
        options = ttk.Frame(panel)
        options.pack(fill='x', pady=10)
        ttk.Label(options, text='Output archive slot: zip').pack(side='left')
        self.slot = tk.StringVar(value=str(settings.get('zip_index', 9)))
        self.slot_entry=ttk.Spinbox(options, from_=2, to=99, width=4, textvariable=self.slot)
        self.slot_entry.pack(side='left')
        ttk.Label(options, text='.360.zip').pack(side='left')
        self.loader_output=tk.BooleanVar(value=settings.get('leave2_loader',False))
        self.loader_check=ttk.Checkbutton(options,text='Leave 2 Loader output',variable=self.loader_output,command=self.update_loader_output)
        self.loader_check.pack(side='right',padx=(12,0))
        self.archive_hint=tk.StringVar()
        ttk.Label(panel,textvariable=self.archive_hint,wraplength=790).pack(anchor='w',pady=(0,6))
        self.update_loader_output()
        self.overwrite = tk.BooleanVar(value=False)
        self.overwrite_check = ttk.Checkbutton(panel, text='Overwrite existing converter output (keeps the previous build in a backup folder)',
                                              variable=self.overwrite)
        self.overwrite_check.pack(anchor='w', pady=(0, 8))
        self.per_map=tk.BooleanVar(value=settings.get('resource_list_mode','per-map')=='per-map')
        self.per_map_check=ttk.Checkbutton(panel,text='Generate per-map resource lists (experimental; recommended for testing)',variable=self.per_map)
        self.per_map_check.pack(anchor='w',pady=(0,4))
        ttk.Label(panel,text='Includes discovered stock and addon dependencies for each map. Uncheck to compare loading without lists.',wraplength=790).pack(anchor='w',pady=(0,8))
        self.retain_hdr=tk.BooleanVar(value=False)
        self.hdr_check=ttk.Checkbutton(panel,text='Retain HDR lighting / use console HDR layout (experimental)',variable=self.retain_hdr)
        self.repair_lengths=tk.BooleanVar(value=False)
        self.repair_check=ttk.Checkbutton(panel,text='Repair stale model length headers (validated bundles only; optional)',variable=self.repair_lengths)
        self.repair_check.pack(anchor='w',pady=(0,8))
        self.allow_missing_navigation=tk.BooleanVar(value=settings.get('allow_missing_navigation',False))
        self.navigation_check=ttk.Checkbutton(panel,text='Survival map / No navigation file',variable=self.allow_missing_navigation)
        self.navigation_check.pack(anchor='w',pady=(0,4))
        self.compatibility_repairs=tk.BooleanVar(value=settings.get('compatibility_repairs',False))
        self.compatibility_check=ttk.Checkbutton(panel,text='Apply compatibility repairs (records omissions and visual replacements)',variable=self.compatibility_repairs)
        self.compatibility_check.pack(anchor='w',pady=(0,4))
        self.include_duplicate_textures=tk.BooleanVar(value=settings.get('include_duplicate_textures',False))
        self.duplicate_texture_check=ttk.Checkbutton(panel,text='Include duplicate textures/materials',variable=self.include_duplicate_textures)
        self.duplicate_texture_check.pack(anchor='w',pady=(0,4))
        ttk.Label(panel,text='Packages referenced PC assets even when already found in game references. Requires PC sources and increases output size.',wraplength=790).pack(anchor='w',pady=(0,6))
        self.force_supplemented_resources=tk.BooleanVar(value=settings.get('force_supplemented_resources',False))
        self.supplement_check=ttk.Checkbutton(panel,text='Force conversion with supplemented resources',variable=self.force_supplemented_resources)
        self.supplement_check.pack(anchor='w',pady=(0,4))
        ttk.Label(panel,text='Uses reported fallbacks for missing materials/textures and enables compatibility repairs.\n'
                  'Missing geometry, invalid files and SDK errors still stop conversion.',wraplength=790).pack(anchor='w',pady=(0,8))
        ttk.Label(panel, text='Requires the project’s patched Xbox runtime for separate addon campaigns.\n'
                  'This tool builds files; installation and a console test are separate steps.',
                  wraplength=790).pack(anchor='w', pady=(0, 8))
        controls = ttk.Frame(footer)
        controls.pack(fill='x')
        self.start = ttk.Button(controls, text='Convert addon', command=self.launch)
        self.start.pack(side='left')
        self.cancel = ttk.Button(controls, text='Cancel after current asset', command=self.stop.set, state='disabled')
        self.cancel.pack(side='left', padx=8)
        self.open = ttk.Button(controls, text='Open output', command=self.open_output)
        self.open.pack(side='right')
        self.install_help_link=ttk.Label(controls,text='Installation instructions',cursor='hand2',
            font=('Segoe UI',9,'underline'),takefocus=True,foreground=self.theme_manager.palette['accent'])
        self.install_help_link.pack(side='right',padx=(6,12))
        self.install_help_link.bind('<Button-1>',lambda event:self.install_help.open())
        self.install_help_link.bind('<Return>',lambda event:self.install_help.open())
        self.install_help_link.bind('<space>',lambda event:self.install_help.open())
        self.status = tk.StringVar(value='Ready')
        ttk.Label(footer, textvariable=self.status,wraplength=790).pack(anchor='w', pady=8)
        self.bar = ttk.Progressbar(footer, mode='indeterminate')
        self.bar.pack(fill='x')
        self.log = tk.Text(footer, height=7, wrap='word', state='disabled')
        self.log.pack(fill='both', expand=True, pady=(8, 0))
        self.build_dlc_tab(settings)
        self.tabs.hide(self.test_tab)
        self.build_container_tab()
        from l4d2_converter.loader_patch_gui import LoaderPatchPage
        patch_tab=ttk.Frame(self.tabs)
        self.tabs.insert(1,patch_tab,text='Loader Patch')
        self.loader_patch_page=LoaderPatchPage(patch_tab,HERE,lambda: not self.running and not self.container_page.running and not (hasattr(self,'offline_page') and self.offline_page.running))
        from l4d2_converter.offline_dlc_gui import OfflineDlcPage
        offline_tab=ttk.Frame(self.tabs)
        self.tabs.insert(2,offline_tab,text='Offline DLC')
        self.offline_page=OfflineDlcPage(offline_tab,HERE,lambda:not self.running and not self.container_page.running and not self.loader_patch_page.running)
        from l4d2_converter.install_help import InstallationHelp
        self.install_help=InstallationHelp(self.tabs)
        self.theme_manager.apply(self.theme_choice.get())
        from l4d2_converter.app_artwork import window_icons
        self.window_icons=window_icons(window,HERE)
        window.protocol('WM_DELETE_WINDOW', self.close)
        window.after(100, self.drain)

    def build_dlc_tab(self, settings):
        from l4d2_converter.dlc import CAMPAIGNS
        values=settings.get('dlc',{})
        panel=ttk.Frame(self.test_tab,padding=14);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='Convert PC DLC campaigns',font=('Segoe UI',12)).pack(anchor='w',pady=(0,10))
        ttk.Label(panel,text='Uses your SDK, Dino D-Day runtime, FFmpeg and clean Xbox reference from the Converter tab.\n'
                  'Produces Leave 2 Loader addon folders and a menu package for the original campaign buttons.',wraplength=790).pack(anchor='w',pady=(0,12))
        form=ttk.Frame(panel);form.pack(fill='x');form.columnconfigure(1,weight=1)
        self.dlc_pc=tk.StringVar(value=values.get('pc_game',settings.get('pc_game','')))
        self.dlc_output=tk.StringVar(value=values.get('output',''))
        for row,(label,variable) in enumerate((('PC L4D2 installation',self.dlc_pc),('Output folder',self.dlc_output))):
            ttk.Label(form,text=label).grid(row=row,column=0,sticky='w',padx=(0,10),pady=5)
            ttk.Entry(form,textvariable=variable).grid(row=row,column=1,sticky='ew',pady=5)
            def browse(value=variable,is_output=row==1):
                if self.running:return
                folder=filedialog.askdirectory(title='Choose DLC conversion output' if is_output else 'Choose PC Left 4 Dead 2 installation',mustexist=not is_output)
                if folder:value.set(folder)
            ttk.Button(form,text='Browse…',command=browse).grid(row=row,column=2,padx=(8,0))
        ttk.Label(panel,text='Campaigns to convert:').pack(anchor='w',pady=(14,4))
        choices=ttk.Frame(panel);choices.pack(fill='x');self.dlc_campaigns={}
        chosen=values.get('campaigns',list(CAMPAIGNS))
        for index,(number,title) in enumerate(CAMPAIGNS.items()):
            value=tk.BooleanVar(value=number in chosen);self.dlc_campaigns[number]=value
            ttk.Checkbutton(choices,text=title,variable=value).grid(row=index//2,column=index%2,sticky='w',padx=(0,45),pady=3)
        self.dlc_supplement=tk.BooleanVar(value=values.get('supplement_missing_materials',False))
        ttk.Checkbutton(panel,text='Supplement missing PC materials/textures with reported stock fallbacks (may change appearance)',variable=self.dlc_supplement).pack(anchor='w',pady=(12,4))
        self.dlc_overwrite=tk.BooleanVar(value=False)
        ttk.Checkbutton(panel,text='Overwrite previous converter output (keeps a backup)',variable=self.dlc_overwrite).pack(anchor='w',pady=(12,4))
        ttk.Label(panel,text='Experimental: The Last Stand is excluded. PC external entity updates are reported but not yet applied.\n'
                  'Successful file conversion still needs console testing, including scripted events and memory usage.',wraplength=790).pack(anchor='w',pady=(0,12))
        controls=ttk.Frame(panel);controls.pack(fill='x')
        self.dlc_start=ttk.Button(controls,text='Convert selected campaigns',command=self.launch_dlc);self.dlc_start.pack(side='left')
        self.dlc_cancel=ttk.Button(controls,text='Cancel after current asset',command=self.stop.set,state='disabled');self.dlc_cancel.pack(side='left',padx=8)
        def open_output():
            p=Path(self.dlc_output.get())
            if p.is_dir():os.startfile(p)
        ttk.Button(controls,text='Register installed addons…',command=self.register_addons).pack(side='right',padx=8)
        ttk.Button(controls,text='Open output',command=open_output).pack(side='right')
        self.dlc_status=tk.StringVar(value='Ready');ttk.Label(panel,textvariable=self.dlc_status).pack(anchor='w',pady=8)
        self.dlc_bar=ttk.Progressbar(panel,mode='indeterminate');self.dlc_bar.pack(fill='x')
        self.dlc_log=tk.Text(panel,height=16,wrap='word',state='disabled');self.dlc_log.pack(fill='both',expand=True,pady=(8,0))

    def register_addons(self):
        if self.running:return
        path=filedialog.askdirectory(title='Choose the installed Xbox game folder (close the game first)')
        if not path:return
        try:
            from l4d2_converter.registration import register_installed_addons
            result=register_installed_addons(path)
            messagebox.showinfo('Addon registration complete',str(len(result['added']))+' new addon folders registered. Existing checkbox choices were preserved.\nFully close and restart the game to mount them.')
        except Exception as error:messagebox.showerror('Cannot register addons',str(error))

    def dlc_settings(self):
        return {'pc_game':self.dlc_pc.get().strip(),'output':self.dlc_output.get().strip(),
                'campaigns':[i for i,value in self.dlc_campaigns.items() if value.get()],
                'supplement_missing_materials':self.dlc_supplement.get()}

    def launch_dlc(self):
        if self.running:return
        from l4d2_converter.dlc import DlcOptions,convert_dlc,campaign_selection
        try:
            settings=self.dlc_settings();campaign_selection(settings['campaigns'])
            if not settings['pc_game'] or not settings['output']:raise ValueError('Choose the PC install and DLC output folders.')
            tools={key:self.fields[key].get().strip() for key in ('sdk_bin','xbox_game','runtime_bin','audio_decoder')}
            if not tools['sdk_bin'] or not tools['xbox_game']:raise ValueError('Set SDK bin and clean Xbox reference on the Converter tab first.')
            options=DlcOptions(**settings,**tools,overwrite=self.dlc_overwrite.get())
            try:saved=json.loads((HERE/'settings.json').read_text(encoding='utf-8'))
            except (OSError,ValueError):saved={}
            saved.update({key:value.get().strip() for key,value in self.fields.items()})
            saved['dlc']=settings;(HERE/'settings.json').write_text(json.dumps(saved,indent=2),encoding='utf-8')
        except Exception as error:
            messagebox.showerror('Cannot start DLC conversion',str(error));return
        self.running=True;self.stop.clear();self.start.configure(state='disabled');self.dlc_start.configure(state='disabled')
        self.dlc_cancel.configure(state='normal');self.dlc_bar.start()
        def worker():
            try:result=convert_dlc(options,progress=lambda s:self.events.put(('dlc_message',s)),cancelled=self.stop.is_set)
            except Exception as error:result={'status':'failed','error':str(error)}
            self.events.put(('dlc_done',result))
        threading.Thread(target=worker,daemon=True).start()

    def browse(self, key, folder=False):
        if self.running:
            return
        if key == 'audio_decoder':
            result=filedialog.askopenfilename(title='Choose your FFmpeg executable',filetypes=[('FFmpeg','ffmpeg.exe'),('Executables','*.exe')])
        elif key == 'input' and not folder:
            result = filedialog.askopenfilename(title='Choose a PC addon VPK', filetypes=[('Valve VPK', '*.vpk')])
        else:
            result = filedialog.askdirectory(title='Choose ' + key.replace('_', ' '), mustexist=key != 'output')
        if result:
            self.fields[key].set(result)
            if key == 'input': self.clear_parts()

    def update_dependency_folder(self):
        same=self.dependency_same.get()
        if same:
            if not self.dependency_was_same:self.dependency_manual=self.fields['dependency_folder'].get()
            source=self.fields['input'].get().strip()
            root=dependency_location(source,same=True) if source else None
            self.fields['dependency_folder'].set(str(root) if root else '')
        elif self.dependency_was_same:
            self.fields['dependency_folder'].set(self.dependency_manual)
        self.dependency_was_same=same
        state='disabled' if same or self.running else 'normal'
        self.entries['dependency_folder'].configure(state=state)
        self.dependency_browse.configure(state=state)

    def update_loader_output(self):
        loader=self.loader_output.get()
        self.slot_entry.configure(state='disabled' if loader or self.running else 'normal')
        self.archive_hint.set('Creates an addon folder for Leave 2 Loader instead of Install. Embedded image first; same-name JPG fallback uses FFmpeg.' if loader else
                              'Use the next consecutive archive slot; leave no gaps.')

    def update_parts_label(self):
        self.parts_label.set(f'Additional parts of the same addon: {len(self.additional_inputs)}')

    def browse_parts(self):
        if self.running: return
        paths = filedialog.askopenfilenames(title='Select other VPK parts of this same addon',filetypes=[('Valve VPK','*.vpk')])
        for path in paths:
            if path != self.fields['input'].get() and path not in self.additional_inputs:
                self.additional_inputs.append(path)
        self.update_parts_label()

    def clear_parts(self):
        if self.running: return
        self.additional_inputs = []
        self.update_parts_label()

    def request_script_repair(self, rows):
        request={'rows':rows,'done':threading.Event(),'accepted':False}
        self.events.put(('script_prompt',request))
        while not request['done'].wait(0.2):
            if self.stop.is_set():raise InterruptedError('Conversion cancelled')
        return request['accepted']

    def request_addon_info(self, details):
        request={'details':details,'done':threading.Event(),'answer':None}
        self.events.put(('metadata_prompt',request))
        while not request['done'].wait(0.2):
            if self.stop.is_set():raise InterruptedError('Conversion cancelled')
        if self.stop.is_set():raise InterruptedError('Conversion cancelled')
        return request['answer']

    def launch(self):
        if self.offline_page.running:
            messagebox.showinfo('Offline DLC','Wait for the native DLC operation to finish.');return
        if self.loader_patch_page.running:
            messagebox.showinfo("Loader Patch", "Wait for the game patch operation to finish."); return
        try:
            settings = {k: v.get().strip() for k, v in self.fields.items()}
            settings['zip_index'] = int(self.slot.get())
            settings['additional_inputs'] = list(self.additional_inputs)
            settings['dependencies_same_as_input']=self.dependency_same.get()
            settings['allow_missing_navigation']=self.allow_missing_navigation.get()
            settings['compatibility_repairs']=self.compatibility_repairs.get()
            settings['leave2_loader']=self.loader_output.get()
            settings['resource_list_mode']='per-map' if self.per_map.get() else 'on-demand'
            settings['retain_hdr_lighting']=self.retain_hdr.get()
            settings['include_duplicate_textures']=self.include_duplicate_textures.get()
            settings['force_supplemented_resources']=self.force_supplemented_resources.get()
            if not all(settings[k] for k in ('input', 'sdk_bin', 'xbox_game', 'output')):
                raise ValueError('Choose the input, SDK bin, Xbox reference, and output folders.')
            options = Options(**settings, overwrite=self.overwrite.get(),repair_model_lengths=self.repair_lengths.get())
            saved=dict(settings)
            saved['dlc']=self.dlc_settings()
            if self.dependency_same.get():saved['dependency_folder']=self.dependency_manual
            (HERE / 'settings.json').write_text(json.dumps(saved, indent=2))
        except Exception as e:
            messagebox.showerror('Cannot start', str(e))
            return
        self.running = True
        self.stop.clear()
        self.start.configure(state='disabled')
        self.dlc_start.configure(state='disabled')
        self.overwrite_check.configure(state='disabled')
        self.loader_check.configure(state='disabled')
        self.update_loader_output()
        self.hdr_check.configure(state='disabled')
        self.per_map_check.configure(state='disabled')
        self.repair_check.configure(state='disabled')
        self.navigation_check.configure(state='disabled')
        self.compatibility_check.configure(state='disabled')
        self.duplicate_texture_check.configure(state='disabled')
        self.supplement_check.configure(state='disabled')
        self.dependency_check.configure(state='disabled')
        self.update_dependency_folder()
        for button in self.buttons:
            button.configure(state='disabled')
        self.cancel.configure(state='normal')
        self.bar.start()
        def worker():
            try:
                result = convert(options, progress=lambda s: self.events.put(('message', s)), cancelled=self.stop.is_set, script_prompt=self.request_script_repair,metadata_prompt=self.request_addon_info)
            except Exception as e:
                result = {'status': 'failed', 'error': str(e)}
            self.events.put(('done', result))
        threading.Thread(target=worker, daemon=True).start()

    def drain(self):
        while True:
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'metadata_prompt':
                try:
                    if not self.stop.is_set():
                        from l4d2_converter.addon_info_gui import edit_addon_info
                        self.status.set('Waiting for addon information…')
                        data['answer']=edit_addon_info(self.window,data['details'],self.stop.set)
                        self.status.set('Continuing conversion…' if not self.stop.is_set() else 'Cancelling…')
                finally:data['done'].set()
                continue
            if kind == 'script_prompt':
                try:
                    if not self.stop.is_set():
                        rows=data['rows']
                        details='\n'.join(row['path']+' (lines '+', '.join(map(str,row['lines']))+')' for row in rows[:8])
                        if len(rows)>8:details+='\n...and '+str(len(rows)-8)+' more scripts.'
                        data['accepted']=messagebox.askyesno('Xbox script compatibility',
                            'Found SpawnSetRule = SPAWN_FINALE in '+str(len(rows))+' script(s).\n\n'
                            'This setting can prevent Director scripts from initializing on Xbox. Remove it from the conversion copy?\n\n'
                            'Removal can change infected spawning behavior. Your original addon stays unchanged.\n\n'+details,
                            parent=self.window)
                finally:data['done'].set()
                continue
            if kind.startswith('dlc_'):
                if kind=='dlc_message':
                    self.dlc_status.set(data);self.dlc_log.configure(state='normal');self.dlc_log.insert('end',data+'\n');self.dlc_log.see('end');self.dlc_log.configure(state='disabled')
                else:
                    self.running=False;self.dlc_bar.stop();self.start.configure(state='normal');self.dlc_start.configure(state='normal');self.dlc_cancel.configure(state='disabled')
                    self.dlc_status.set(data['status'])
                    if data['status']=='converted-awaiting-console-test':messagebox.showinfo('PC campaigns ready','Converted folders are in Addons inside the output folder. Read INSTALL.txt before testing. Console compatibility is unverified.')
                    else:messagebox.showwarning('DLC conversion: '+data['status'],data.get('error') or 'See report.json and the individual campaign reports. Only successful campaigns are included in Addons.')
                continue
            if kind == 'message':
                self.status.set(data)
                self.log.configure(state='normal')
                self.log.insert('end', data + '\n')
                self.log.see('end')
                self.log.configure(state='disabled')
            else:
                self.running = False
                self.bar.stop()
                self.start.configure(state='normal')
                self.dlc_start.configure(state='normal')
                self.overwrite_check.configure(state='normal')
                self.loader_check.configure(state='normal')
                self.update_loader_output()
                self.hdr_check.configure(state='normal')
                self.per_map_check.configure(state='normal')
                self.repair_check.configure(state='normal')
                self.navigation_check.configure(state='normal')
                self.compatibility_check.configure(state='normal')
                self.duplicate_texture_check.configure(state='normal')
                self.supplement_check.configure(state='normal')
                self.dependency_check.configure(state='normal')
                for button in self.buttons:
                    button.configure(state='normal')
                self.update_dependency_folder()
                self.cancel.configure(state='disabled')
                self.status.set(data['status'])
                if data['status'] == 'converted-awaiting-console-test':
                    messagebox.showinfo('Build complete', 'Converted files are ready in the output folder.\nRead INSTALL.txt and TEXTURE-BUDGET.txt before testing on your console.' + ('\nNOTE: Optional addon preview was omitted; see report.json and the conversion log.' if data.get('leave2_loader',{}).get('preview',{}).get('status')=='omitted' else '') + ('\nWARNING: Missing resources were replaced with visual fallbacks. Read SUPPLEMENTED-RESOURCES.txt.' if data.get('supplemented_resources') else ''))
                elif data['status'] == 'diagnostic-with-unresolved-source-references':
                    messagebox.showwarning('Diagnostic build only', 'A test package was created, but original animation references remain unresolved.\nRead UNRESOLVED-SOURCE-REFERENCES.txt and SUPPLEMENTED-RESOURCES.txt.\nThis is not a complete conversion and may crash on console.')
                else:
                    failures = data.get('failures', [])
                    details = '\n'.join(f'{f.get("path", "Package")}: {f.get("reason", "Missing dependency")}' for f in failures[:5])
                    messagebox.showerror('Conversion did not complete', data.get('error') or
                        (f'{len(failures)} unresolved failures.\n{details}\n\nSee report.json and logs for details.' if failures else 'See report.json for details.'))
        self.window.after(100, self.drain)

    def build_container_tab(self):
        from l4d2_converter.container_gui import ContainerPage
        page = ttk.Frame(self.tabs)
        self.tabs.add(page, text='Xbox game files')
        def busy_changed(busy):
            state = 'disabled' if busy or self.running else 'normal'
            self.start.configure(state=state)
            self.dlc_start.configure(state=state)
        self.container_page = ContainerPage(page, HERE, busy_changed, lambda: not self.running and not (hasattr(self,"loader_patch_page") and self.loader_patch_page.running) and not (hasattr(self,'offline_page') and self.offline_page.running))

    def open_output(self):
        path = Path(self.fields['output'].get())
        if path.is_dir():
            os.startfile(path)

    def close(self):
        if self.offline_page.running:
            messagebox.showinfo('Offline DLC','Wait for the native DLC operation to finish, or cancel the current build before closing.');return
        if self.loader_patch_page.running:
            messagebox.showinfo("Loader Patch", "Wait for the game patch operation to finish before closing."); return
        if self.container_page.running:
            self.container_page.close()
            self.status.set('Stopping Xbox file operation; close again when it finishes.')
            return
        if self.running:
            self.stop.set()
            self.status.set('Cancelling; wait for the current asset to finish before closing.')
        else:
            self.container_page.destroy()
            self.window.destroy()


if __name__ == '__main__':
    if '--self-check' in sys.argv:
        from l4d2_converter.release_check import run_check
        test_job=Path(sys.argv[sys.argv.index('--test-job')+1]) if '--test-job' in sys.argv else None
        run_check(App,HERE,Path(sys.argv[sys.argv.index('--self-check')+1]),test_job)
        raise SystemExit(0)
    root = tk.Tk()
    App(root)
    root.mainloop()
