"""Non-destructive, hidden startup check used to validate release packaging."""
from pathlib import Path
import json,tkinter as tk,subprocess,sys,hashlib
from .app_paths import source_fingerprint
from .loader_patcher import LoaderPatcher

def run_check(app_class,home,report_path,test_job=None):
    report={'status':'checking','frozen':bool(getattr(sys,'frozen',False)),'home':str(home),'checks':{}}
    root=tk.Tk();root.withdraw()
    try:
        app=app_class(root);root.update_idletasks()
        checks=report['checks'];checks['gui_constructed']=True
        checks['assets_loaded']=(home/'assets/app/vanilla.png').is_file()
        checks['patch_manifest']=len(LoaderPatcher(home/'tools/loader-patch').manifest['files'])==27
        checks['source_fingerprint']=len(source_fingerprint())==64
        checks['no_personal_settings']=not any((home/n).exists() for n in ('settings.json','loader-patch-settings.json','offline-dlc-settings.json','container-settings.json'))
        exe=home/'tools/x360-convert/bin/x360-convert.exe'
        result=subprocess.run([str(exe),'--help'],capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        checks['container_tool']=result.returncode==0
        checks['public_title']=root.title()=='Leave 2 Converter Vanilla v0.5 Public Beta'
        if test_job:
            from .core import Options,convert
            job=json.loads(Path(test_job).read_text(encoding='utf-8'));source=Path(job['options']['input'])
            before=hashlib.sha256(source.read_bytes()).hexdigest()
            result=convert(Options(**job['options']),progress=lambda _:None,metadata_prompt=lambda _:job['metadata'])
            report['conversion']={k:result.get(k) for k in ('status','error','failures','backend_sha256','converter_source_sha256')}
            checks['real_conversion']=result['status']=='converted-awaiting-console-test'
            checks['source_input_unchanged']=hashlib.sha256(source.read_bytes()).hexdigest()==before
        app.container_page.destroy()
        report['status']='passed' if all(checks.values()) else 'failed'
    except Exception as error:
        report.update(status='failed',error=str(error));raise
    finally:
        root.destroy();Path(report_path).write_text(json.dumps(report,indent=2),encoding='utf-8')
    if report['status']!='passed':raise RuntimeError('Release startup check failed')
