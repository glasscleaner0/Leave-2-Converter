"""Optional independent Rust backend. No SDK DLLs or SDK preprocessing.

Selecting a makegamedata-rs*.exe explicitly opts in. Settings are an adjacent
makegamedata-rs.settings.json; absent settings preserve source visual policies.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import time
from .archive import safe_name
from .formats import validate_asset
from .models import model_info


def digest(data):
    return hashlib.sha256(data).hexdigest()


def selected_executable(value):
    path = Path(value)
    return path if path.is_file() and path.name.lower().startswith('makegamedata-rs') and path.suffix.lower() == '.exe' else None


class RustBackend:
    native = True

    def __init__(self, exe, work, timeout, rows, cancelled=lambda: False):
        self.exe = Path(exe).resolve()
        self.work = Path(work)
        self.work.mkdir(parents=True, exist_ok=True)
        self.game = self.work / 'game/left4dead2'
        self.game.mkdir(parents=True)
        self.logs = self.work.parent / 'logs'
        self.logs.mkdir()
        self.timeout, self.rows, self.cancelled = timeout, rows, cancelled
        self.hash = digest(self.exe.read_bytes())
        self.serial = 0
        self.selection = None
        self.settings = {
            'vtx_layout': 'legacy', 'visual': 'no-changes',
            'texture_format': 'preserve', 'thumbnail': 'refuse',
            'cubemap': 'preserve', 'mips': 'preserve', 'crc': 'preserve',
            'hdr_textures': 'preserve',
        }
        choices = {
            'vtx_layout': ('legacy','extended'), 'visual': ('no-changes','allow-changes'),
            'texture_format': ('preserve','bgra8888','bgra-if-needed'),
            'thumbnail': ('refuse','srgb-average'), 'cubemap': ('preserve','six-faces'),
            'mips': ('preserve','honor-nomip'), 'crc': ('preserve','drop'),
            'hdr_textures': ('preserve','use-ldr'),
        }
        settings_path = self.exe.parent / 'makegamedata-rs.settings.json'
        if settings_path.exists():
            if settings_path.stat().st_size > 65536:
                raise ValueError('Rust settings exceed 64 KiB')
            supplied = json.loads(settings_path.read_text(encoding='utf-8'))
            if not isinstance(supplied, dict) or any(k not in choices or v not in choices[k] for k,v in supplied.items()):
                raise ValueError('Unknown Rust backend setting or value')
            self.settings.update(supplied)
        if self.settings['visual'] == 'no-changes' and any(self.settings[k] != 'preserve' for k in ('texture_format','cubemap','mips','hdr_textures')):
            raise ValueError('Rust visual changes require explicit visual=allow-changes')
        code, capabilities, _ = self._invoke(['--capabilities'], 'capabilities')
        if code or capabilities.get('backend') != 'makegamedata-rs' or capabilities.get('protocol_version') != 1 or capabilities.get('requires_proprietary_sdk') is not False:
            raise ValueError('Unsupported independent Rust backend capability contract')
        self.capabilities = capabilities

    def close(self):
        pass

    def _invoke(self, args, label):
        if self.cancelled():
            raise InterruptedError('Conversion cancelled')
        if digest(self.exe.read_bytes()) != self.hash:
            raise ValueError('Rust executable changed during the job')
        self.serial += 1
        log = self.logs / ('rust-%04d-%s.json' % (self.serial,label))
        errors = log.with_suffix('.stderr.txt')
        cancel = self.work / 'rust-cancel.request'
        started = time.monotonic()
        with log.open('xb') as out, errors.open('xb') as err:
            process = subprocess.Popen([str(self.exe), *map(str,args)], cwd=self.game,
                stdout=out, stderr=err,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            try:
                while True:
                    try:
                        code = process.wait(timeout=0.2)
                        break
                    except subprocess.TimeoutExpired:
                        if self.cancelled():
                            cancel.touch(exist_ok=True)
                            try: process.wait(timeout=2)
                            except subprocess.TimeoutExpired: process.kill(); process.wait()
                            raise InterruptedError('Conversion cancelled; Rust diagnostics retained')
                        if time.monotonic()-started > self.timeout:
                            process.kill(); process.wait()
                            raise ValueError('Rust conversion timed out; incomplete outputs are not used')
                        if log.stat().st_size > 16*1024*1024 or errors.stat().st_size > 1024*1024:
                            process.kill(); process.wait()
                            raise ValueError('Rust diagnostics exceed the output limit')
            finally:
                if process.poll() is None:
                    process.kill(); process.wait()
        if log.stat().st_size > 16*1024*1024:
            raise ValueError('Rust JSON result exceeds 16 MiB')
        raw = log.read_text(encoding='utf-8')
        try: report = json.loads(raw)
        except (ValueError,UnicodeError) as exc:
            if code:
                detail=errors.read_bytes()[:8192].decode('utf-8',errors='replace')
                report={'requested_outputs_complete':False,'diagnostic':{'stage':'native_command','message':detail.strip() or 'No JSON result; see '+log.name}}
            else:
                raise ValueError('Rust did not return a valid JSON result; see '+log.name) from exc
        if not isinstance(report,dict):
            raise ValueError('Rust result must be one JSON object')
        return code, report, log.name

    def preflight(self, members, dependencies):
        """Keep staged PC files and selected console supplements visibly separate."""
        selected = {}
        for path in sorted(self.game.rglob('*')):
            if not path.is_file(): continue
            name = safe_name(path.relative_to(self.game).as_posix())
            if name.startswith('models/') and name.endswith(('.mdl','.vvd','.vtx','.phy','.ani')):
                if name.endswith(('.dx80.vtx','.sw.vtx','.xbox.vtx')): continue
                selected[name] = (path,'staged-input-or-resolved-pc','staged-pc-root')
        extra = self.work / 'rust-console-selection'
        for name,data in sorted(members.items()):
            if not name.startswith('models/') or not name.endswith(('.mdl','.vvd','.vtx','.phy','.ani')): continue
            name = safe_name(name)
            if name in selected: raise ValueError('Conflicting staged and supplemental model resource: '+name)
            path = extra / name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(data)
            selected[name] = (path,'selected-console-supplement','console-supplement')
        if len(selected)>10000: raise ValueError('Selected model resources exceed 10000 members')
        owners = {}
        for name,(path,_,_) in selected.items():
            if name.endswith('.mdl'):
                info=model_info(path.read_bytes())
                ani=info.get('animation_file')
                if ani:
                    ani=safe_name(ani)
                    if '.360.' in name and '.360.' not in ani:
                        ani=Path(ani).with_suffix('.360'+Path(ani).suffix).as_posix()
                    if ani in owners and owners[ani]!=name: raise ValueError('Ambiguous animation owner: '+ani)
                    owners[ani]=name
        rows=[]
        for name,(path,origin,bundle) in selected.items():
            fields=[name,str(path),origin,bundle]
            if name.endswith('.ani'):
                if name not in owners: raise ValueError('Animation dependency has no declaring MDL: '+name)
                fields.append(owners[name])
            if any('\t' in s or '\n' in s or '\r' in s for s in fields): raise ValueError('Model manifest field contains a separator')
            rows.append('\t'.join(fields))
        record={'staged_origin_scope':'input files and resolved PC references share a staging root; archive-level origin is not inferred',
                'resolver_reference_edges':dependencies.get('reference_edges',{}), 'selected_members':len(rows)}
        if rows:
            self.selection=self.work/'rust-model-selection.tsv'
            self.selection.write_text('\n'.join(rows)+'\n',encoding='utf-8')
            code,result,log=self._invoke(['--inspect-model-selection',self.selection],'selection')
            record.update(result=result,log=log)
            self.selection_report=record
            if code or result.get('selection_checks_passed') is not True:
                raise ValueError('Rust model selection rejected: '+'; '.join(result.get('errors',[]))[:4000])
        return record

    def run(self, pattern, expected):
        started=time.monotonic()
        row={'pattern':pattern,'expected':expected,'backend':'makegamedata-rs','settings':dict(self.settings)}
        outputs={}
        try:
            for name in expected:
                if safe_name(name)!=name: raise ValueError('Unsafe or noncanonical target resource')
            if pattern.endswith('.*'):
                model=safe_name(pattern[:-2]+'.mdl')
                target=self.work/('rust-model-%04d'%self.serial)
                args=['--convert-model-family','l4d2-pc',self.settings['vtx_layout'],self.game,model,target,
                      '--cancel-file',self.work/'rust-cancel.request']
                code,result,log=self._invoke(args,'model')
                row.update(exit=code,result=result,log=log)
                root=target/'content'
                if code or result.get('requested_outputs_complete') is not True:
                    raise ValueError('Rust model family failed: '+str(result.get('diagnostic',{}).get('message',''))+'; see '+log)
                for name in expected:
                    outputs[name]=(root/name).read_bytes()
            else:
                source=safe_name(pattern)
                if len(expected)!=1: raise ValueError('Non-model Rust jobs require exactly one output')
                target=self.work/('rust-job-%04d'%self.serial)
                target.mkdir()
                manifest=target/'jobs.tsv'
                destination=target/expected[0]
                destination.parent.mkdir(parents=True,exist_ok=True)
                values=[str(self.game/source),str(destination)]
                if any(any(c in v for c in '\t\r\n') for v in values): raise ValueError('Manifest path contains a separator')
                manifest.write_text('\t'.join(values)+'\n',encoding='utf-8')
                args=['--run-jobs','--source','l4d2-pc','--target','l4d2-x360','--hdr','off',
                    '--cancel-file',self.work/'rust-cancel.request']
                for key in ('visual','texture_format','thumbnail','cubemap','mips','crc','hdr_textures'):
                    args.extend(['--'+key.replace('_','-'),self.settings[key]])
                if self.selection: args.extend(['--model-selection',self.selection])
                code,result,log=self._invoke([*args,manifest],'job')
                row.update(exit=code,result=result,log=log)
                if code or result.get('failed')!=0 or result.get('requested_outputs_complete') is not True:
                    messages=[str(f.get('diagnostic',{}).get('message','')) for f in result.get('files',[]) if f.get('diagnostic')]
                    raise ValueError('Rust conversion failed: '+'; '.join(messages)[:3000]+'; see '+log)
                outputs[expected[0]]=destination.read_bytes()
            for name,data in outputs.items(): validate_asset(name,data)
            row.update(exit=code,success=True,log=log,result=result,
                outputs={n:{'bytes':len(b),'sha256':digest(b)} for n,b in outputs.items()})
        except InterruptedError:
            row.update(success=False,error='Cancelled',seconds=round(time.monotonic()-started,3))
            self.rows.append(row)
            raise
        except Exception as exc:
            row.update(success=False,error=str(exc));outputs={}
        row['seconds']=round(time.monotonic()-started,3)
        self.rows.append(row)
        return outputs
