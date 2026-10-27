"""Small built-in ttk palette layer; no external theme dependency."""
from pathlib import Path
import json
from tkinter import ttk,TclError

PALETTES={
    'Light':dict(bg='#f3f4f6',panel='#ffffff',field='#ffffff',fg='#20242b',muted='#657080',border='#bdc4ce',active='#e4e8ef',accent='#ad3535',disabled='#e8ebef'),
    'Dark':dict(bg='#202328',panel='#2a2e35',field='#171a1f',fg='#edf0f5',muted='#929ba8',border='#444c58',active='#383f49',accent='#b94747',disabled='#292e35'),
}
CHOICES=('System','Light','Dark')
def system_mode():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
            return 'Light' if winreg.QueryValueEx(key,'AppsUseLightTheme')[0] else 'Dark'
    except (ImportError,OSError):return 'Light'

class ThemeManager:
    def __init__(self,root,settings):
        self.root=root;self.settings=Path(settings);self.style=ttk.Style(root)
        # Keep one base theme while switching palettes, preserving custom image
        # elements such as the two-sided medkit button across live changes.
        self.style.theme_use('clam')
        try:
            saved=json.loads(self.settings.read_text(encoding='utf-8'))
            mode=saved.get('theme','System') if isinstance(saved,dict) else 'System'
        except (OSError,ValueError):mode='System'
        self.mode=mode if mode in CHOICES else 'System'
        self.apply(self.mode)
    def apply(self,mode,persist=False):
        if mode not in CHOICES:raise ValueError('Unknown appearance theme')
        self.mode=mode;self.resolved=system_mode() if mode=='System' else mode
        p=PALETTES[self.resolved];self.palette=p;s=self.style
        self.root.tk_setPalette(background=p['bg'],foreground=p['fg'],activeBackground=p['active'],activeForeground=p['fg'],selectBackground=p['accent'],selectForeground='#ffffff')
        s.configure('.',background=p['bg'],foreground=p['fg'],bordercolor=p['border'],troughcolor=p['field'],selectbackground=p['accent'],selectforeground='#ffffff',fieldbackground=p['field'],insertcolor=p['fg'])
        s.configure('TFrame',background=p['bg']);s.configure('TLabel',background=p['bg'],foreground=p['fg'])
        s.configure('TButton',background=p['panel'],foreground=p['fg'],bordercolor=p['border'],lightcolor=p['panel'],darkcolor=p['panel'],padding=(7,4))
        s.map('TButton',background=[('disabled',p['disabled']),('pressed',p['accent']),('active',p['active'])],foreground=[('disabled',p['muted']),('pressed','#ffffff'),('!disabled',p['fg'])])
        for name in ('TEntry','TSpinbox','TCombobox'):
            s.configure(name,fieldbackground=p['field'],background=p['panel'],foreground=p['fg'],arrowcolor=p['fg'],bordercolor=p['border'],lightcolor=p['border'],darkcolor=p['border'])
            s.map(name,fieldbackground=[('disabled',p['disabled']),('readonly',p['field'])],foreground=[('disabled',p['muted']),('!disabled',p['fg'])],selectbackground=[('!disabled',p['accent'])],selectforeground=[('!disabled','#ffffff')])
        for name in ('TCheckbutton','TRadiobutton'):
            s.configure(name,background=p['bg'],foreground=p['fg'],indicatorbackground=p['field'],indicatorforeground=p['fg'],bordercolor=p['border'])
            s.map(name,background=[('active',p['bg'])],foreground=[('disabled',p['muted']),('!disabled',p['fg'])],indicatorbackground=[('disabled',p['disabled']),('selected',p['accent']),('!selected',p['field'])])
        s.configure('TNotebook',background=p['bg'],bordercolor=p['border'])
        s.configure('TNotebook.Tab',background=p['panel'],foreground=p['muted'],padding=(13,7))
        s.map('TNotebook.Tab',background=[('selected',p['active']),('active',p['panel'])],foreground=[('selected',p['fg']),('active',p['fg'])])
        for name in ('Horizontal.TProgressbar','Vertical.TProgressbar'):
            s.configure(name,background=p['accent'],troughcolor=p['field'],bordercolor=p['border'],lightcolor=p['accent'],darkcolor=p['accent'])
        for name in ('Vertical.TScrollbar','Horizontal.TScrollbar'):
            s.configure(name,background=p['panel'],troughcolor=p['field'],arrowcolor=p['fg'],bordercolor=p['border'],lightcolor=p['panel'],darkcolor=p['panel'])
            s.map(name,background=[('active',p['active'])])
        self.root.option_add('*TCombobox*Listbox.background',p['field'])
        self.root.option_add('*TCombobox*Listbox.foreground',p['fg'])
        self.root.option_add('*TCombobox*Listbox.selectBackground',p['accent'])
        self.root.option_add('*TCombobox*Listbox.selectForeground','#ffffff')
        self._widgets(self.root)
        if persist:
            try:
                self.settings.parent.mkdir(parents=True,exist_ok=True)
                temp=self.settings.with_suffix('.tmp');temp.write_text(json.dumps({'theme':mode},indent=2),encoding='utf-8');temp.replace(self.settings)
            except OSError:return False
        return True
    def _widgets(self,parent):
        p=self.palette
        for widget in parent.winfo_children():
            kind=widget.winfo_class()
            if kind=='Canvas':
                widget.configure(background=p['bg'])
            elif kind in ('Text','Listbox'):
                widget.configure(background=p['field'],foreground=p['fg'],selectbackground=p['accent'],selectforeground='#ffffff',highlightbackground=p['border'],highlightcolor=p['accent'])
                if kind=='Text':widget.configure(insertbackground=p['fg'])
            elif kind=='TCombobox':
                try:
                    pop=widget.tk.call('ttk::combobox::PopdownWindow',str(widget))
                    widget.tk.call(str(pop)+'.f.l','configure','-background',p['field'],'-foreground',p['fg'],'-selectbackground',p['accent'],'-selectforeground','#ffffff')
                except TclError:pass
            self._widgets(widget)
