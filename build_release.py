"""Build the local, portable Windows application. No game/SDK downloads."""
from pathlib import Path
import sys,os,subprocess,shutil,json,hashlib

ROOT=Path(__file__).resolve().parent
NAME='Leave 2 Converter Vanilla'

def main():
    if sys.platform!='win32':raise SystemExit('Build the Windows application on Windows.')
    dist=ROOT/'dist';target=dist/NAME
    if target.exists():raise SystemExit('Release output already exists; preserve it before building again.')
    build=ROOT/'.build';build.mkdir(exist_ok=True)
    version_file=build/'version.txt'
    version_file.write_text('''VSVersionInfo(ffi=FixedFileInfo(filevers=(0,5,0,0),prodvers=(0,5,0,0),mask=0x3f,flags=0,OS=0x40004,fileType=0x1,subtype=0x0,date=(0,0)),kids=[StringFileInfo([StringTable('040904B0',[StringStruct('CompanyName','Leave 2 Converter contributors'),StringStruct('FileDescription','Leave 2 Converter Vanilla'),StringStruct('FileVersion','0.5.0.0'),StringStruct('ProductName','Leave 2 Converter Vanilla'),StringStruct('ProductVersion','0.5 Public Beta'),StringStruct('OriginalFilename','Leave 2 Converter Vanilla.exe')])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])''',encoding='utf-8')
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed',
        '--name',NAME,'--distpath',str(dist),'--workpath',str(build/'pyinstaller'),'--specpath',str(build),
        '--paths',str(ROOT),'--collect-submodules','l4d2_converter','--icon',str(ROOT/'assets/app/vanilla.png'),
        '--version-file',str(version_file),str(ROOT/'gui.py')]
    subprocess.run(command,cwd=ROOT,check=True)
    for folder in ('assets','tools','THIRD-PARTY-NOTICES'):
        shutil.copytree(ROOT/folder,target/folder)
    for name in ('README.md','INSTALLATION.md','NOTICE.md','LICENSE','CHANGELOG.md','BUILDING.md','BUILD-INFO.json'):
        shutil.copy2(ROOT/name,target/name)
    from l4d2_converter.app_paths import source_fingerprint
    info=json.loads((target/'BUILD-INFO.json').read_text());info.update(converter_source_sha256=source_fingerprint(),
        python_version=sys.version.split()[0],kind='windows-x64-portable')
    (target/'BUILD-INFO.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
    sums=[]
    for p in sorted(target.rglob('*')):
        if p.is_file():sums.append(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(target).as_posix())
    (target/'SHA256SUMS.txt').write_text('\n'.join(sums)+'\n',encoding='utf-8')
    print(target)

if __name__=='__main__':main()
