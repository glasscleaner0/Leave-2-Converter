"""On-demand installation page; hidden from the normal notebook tabs."""
import tkinter as tk
from tkinter import ttk

SECTIONS = [
    ('Start here',
     'These instructions are for converted addons, not PC VPK files. Your Xbox game must be extracted into a folder containing default.xex. Leave 2 Loader requires a console capable of running the modified game files. Keep a backup before changing your game.'),
    ('1. Prepare the game once',
     'Open the Loader Patch tab. Select the extracted game folder containing default.xex, then apply the patch. This installs Leave 2 Loader and integrates the official title update. Disable the separate L4D2 title update in Aurora for this patched copy. Launch default.xex from this same game folder when testing.'),
    ('2. Choose the output type BEFORE converting',
     'For the easiest installation, turn ON “Leave 2 Loader output” in the Converter tab. Convert the addon, then click Open output. A successful conversion creates an addon folder with addoninfo.txt and zip0.360.zip directly inside it. Campaigns may also have maps and missions folders; previews may have a ui folder. Keep all of these together.'),
    ('3. Copy the ADDON folder, not its output parent',
     'Close the game before copying files. Find the folder that directly contains addoninfo.txt and zip0.360.zip. Copy THAT whole folder into left4dead2\\addons inside your patched game. Create addons if needed. Do not copy an extra conversion-output parent around it.'),
    ('Example: correct folder layout',
     'YourGame\\\n'
     '  default.xex\n'
     '  left4dead2\\\n'
     '    addons\\\n'
     '      Titanic\\\n'
     '        addoninfo.txt\n'
     '        zip0.360.zip\n'
     '        maps\\       (if provided)\n'
     '        missions\\   (if provided)\n'
     '        ui\\         (if provided)\n\n'
     'WRONG: addons\\My-Conversion-Output\\Titanic\\addoninfo.txt\n'
     'RIGHT: addons\\Titanic\\addoninfo.txt'),
    ('4. Keep the package intact',
     'Do NOT unzip zip0.360.zip into the addon folder. Do NOT move it into the main left4dead2 folder. Do NOT rename its internal files or discard loose maps, missions, or ui. Each separate addon folder can contain its own zip0.360.zip; those names do not conflict because the folders are separate. The Xbox does not load the original PC .vpk as a converted addon.'),
    ('5. Restart, detect, and enable',
     'Start the patched game from a fresh launch. On the main menu, open ADD-ONS to enter Leave 2 Loader. The new addon should be detected automatically. Select it and use its enabled/disabled checkbox icon to enable it. If you changed addon states, use RESTART GAME to apply them. If restarting freezes in your emulator, close the emulator and launch default.xex again. A yellow addon name indicates a changed setting, not an installation error.'),
    ('6. Launch or check the addon',
     'Campaign: open the campaign selector for your chosen mode, choose Addon Campaigns, and select the campaign. Survival map: use Survival and its Addon Campaigns selector. An addon only appears in modes declared by its mission file. Texture/model/HUD/sound replacement: launch a map that uses the replaced content; it normally does not add a campaign entry.'),
    ('If you converted WITHOUT Leave 2 Loader output',
     'This is the older manual format. Follow INSTALL.txt in that conversion output. It usually provides Install\\left4dead2 with loose maps/missions and a root zipN.360.zip. Merge that content into the game’s left4dead2 folder without overwriting another addon. Root archive numbers must be consecutive from zip0, with no gaps. The “next root ZIP slot” rule applies only to this manual format—not to zip0 inside separate Loader addon folders. Reconvert with Leave 2 Loader output enabled if you want the simpler folder installation above.'),
    ('L4D1 survivors and native Offline DLC',
     'Campaigns using Bill, Zoey, Louis, or Francis need the L4D1 survivor support when the original DLC is not mounted. The survivor-only importer supplies bodies, materials, and arms. Full Offline DLC builds also prepare startup dialogue registration. Use Offline DLC → Install prepared build for those full builds; copying only the Addons folders omits the separate startup archive. Keep the required DLC/support addons enabled and apply the current Loader Patch for the audio fixes.'),
    ('Troubleshooting: missing from ADD-ONS',
     'Check that you launched the patched default.xex from the game copy you edited. Check the folder layout above: addoninfo.txt must be directly inside the addon folder, not one folder deeper. Restart fully and open ADD-ONS again. Do not edit addonlist.txt unless diagnosing a specific problem. In Xenia, game-folder writes must be enabled for automatic detection/state saving.'),
    ('Troubleshooting: listed, but not working',
     'Confirm the addon is enabled and restart after changes. Remove an older duplicate of the same addon. Two addons replacing the same resource can conflict, so temporarily disable the other replacement. An entry in ADD-ONS confirms detection, not a successful campaign conversion. Check report.json and the game log for missing assets, unsupported scripts, or loading failures.'),
    ('Troubleshooting: campaign missing or crash',
     'Keep all converted maps/missions and all supplied campaign parts. Check the correct game mode. Do not treat a failed or incomplete conversion as ready to install; inspect report.json first. If a campaign crashes on console but works in Xenia, retain the log and test with unrelated addons disabled. Successful conversion does not guarantee hardware compatibility.'),
]


class InstallationHelp:
    def __init__(self,tabs):
        self.tabs=tabs;self.previous=None
        self.page=ttk.Frame(tabs,padding=16)
        tabs.add(self.page,text='Installation Instructions');tabs.hide(self.page)
        header=ttk.Frame(self.page);header.pack(fill='x',pady=(0,10))
        ttk.Label(header,text='Installing converted addons',font=('Segoe UI',17,'bold')).pack(side='left')
        ttk.Button(header,text='Back',command=self.back).pack(side='right')
        body=ttk.Frame(self.page);body.pack(fill='both',expand=True)
        scroll=ttk.Scrollbar(body,orient='vertical');scroll.pack(side='right',fill='y')
        self.text=tk.Text(body,wrap='word',padx=12,pady=10,font=('Segoe UI',11),
                          yscrollcommand=scroll.set,borderwidth=0,highlightthickness=0)
        self.text.pack(fill='both',expand=True);scroll.configure(command=self.text.yview)
        self.text.tag_configure('heading',font=('Segoe UI',12,'bold'),spacing1=15,spacing3=6)
        self.text.tag_configure('body',spacing3=10)
        self.text.tag_configure('example',font=('Consolas',10),spacing3=10)
        for heading,body in SECTIONS:
            self.text.insert('end',heading+'\n','heading')
            self.text.insert('end',body+'\n\n','example' if heading.startswith('Example:') else 'body')
        self.text.configure(state='disabled')
        tabs.bind('<<NotebookTabChanged>>',self.changed,add='+')

    def open(self,_event=None):
        current=self.tabs.select()
        if current!=str(self.page):self.previous=current
        self.tabs.add(self.page,text='Installation Instructions')
        self.tabs.select(self.page);self.text.yview_moveto(0)

    def back(self):
        if self.previous and self.previous in self.tabs.tabs():self.tabs.select(self.previous)
        else:self.tabs.select(0)
        self.tabs.hide(self.page)

    def changed(self,_event=None):
        if self.tabs.select()!=str(self.page) and self.tabs.tab(self.page,'state')!='hidden':
            self.tabs.hide(self.page)
