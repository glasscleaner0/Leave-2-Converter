"""Integration checks. Original utilities are optional external test oracles only."""
import argparse, hashlib, json, pathlib, struct, subprocess, time

p=argparse.ArgumentParser()
p.add_argument('--exe',required=True,type=pathlib.Path)
p.add_argument('--work',required=True,type=pathlib.Path)
p.add_argument('--game',type=pathlib.Path)
p.add_argument('--exiso',type=pathlib.Path)
a=p.parse_args()
root=a.work.resolve(); root.mkdir(parents=True,exist_ok=False)
exe=str(a.exe.resolve()); checks=[]

def run(*args):
    start=time.monotonic()
    command=[exe,*map(str,args),'--quiet']
    result=subprocess.run(command,capture_output=True,text=True)
    checks.append({'command':list(map(str,args)),'exit':result.returncode,'seconds':round(time.monotonic()-start,3),'stdout':result.stdout,'stderr':result.stderr})
    (root/'validation.json').write_text(json.dumps(checks,indent=2))
    if result.returncode: raise RuntimeError(result.stderr)
    print('PASS',args[0],*(str(x) for x in args[1:3]),flush=True)
    return result.stdout

def digest(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()

def tree(p):
    return {str(f.relative_to(p)).replace('\\','/'): (f.stat().st_size,digest(f)) for f in p.rglob('*') if f.is_file()}

def same(x,y,label):
    assert x==y,label
    checks.append({'check':label,'passed':True})
    (root/'validation.json').write_text(json.dumps(checks,indent=2))
    print('PASS',label,flush=True)

def package(p):
    return next(f for f in p.iterdir() if f.is_file())

src=root/'synthetic'; src.mkdir()
for folder in ['empty','empty2','nested/sub','names']: (src/folder).mkdir(parents=True,exist_ok=True)
for i in range(320):
    # Unequal name lengths exercise tree ordering and sector boundary packing.
    name=f'{i:04}_'+('x'*(i%120))+'.bin'
    (src/'names'/name).write_bytes(bytes([i%256])*(i*17))
(src/'zero').write_bytes(b'')
(src/'nested/sub/data.bin').write_bytes(bytes(range(256))*1234)
xex=bytearray(128);xex[:4]=b'XEX2';struct.pack_into('>I',xex,20,1);struct.pack_into('>II',xex,24,0x40006,64)
struct.pack_into('>IIII',xex,64,0x12345678,1,1,0x454108d4);xex[80:84]=bytes([2,0,1,1])
(src/'default.xex').write_bytes(xex)
# Cross both hash-group and fragment boundaries.
with (src/'large.bin').open('wb') as f:
    chunk=bytes(range(256))*4096
    for _ in range(164): f.write(chunk)

iso=root/'synthetic.iso';run('iso',src,iso)
run('inspect',iso)
unpacked=root/'synthetic-extracted';run('extract',iso,unpacked);same(tree(src),tree(unpacked),'synthetic ISO extraction preserves all files')
g=root/'synthetic-god';run('god',iso,g,'--title','Integration test');pkg=package(g);run('verify-god',pkg)
reiso=root/'synthetic-roundtrip.iso';run('iso',pkg,reiso);same(digest(iso),digest(reiso),'synthetic ISO GOD ISO is byte identical')
gfolder=root/'synthetic-folder-god';run('god',src,gfolder,'--title','Integration test');run('verify-god',package(gfolder))
unpackedgod=root/'synthetic-god-extracted';run('extract',pkg,unpackedgod);same(tree(src),tree(unpackedgod),'synthetic direct GOD extraction preserves all files')
before=digest(iso);r=subprocess.run([exe,'iso',src,str(iso)],capture_output=True,text=True)
same((r.returncode,digest(iso)),(1,before),'existing output refused without changes')

# A deliberately cyclic directory tree must be rejected before extraction.
bad=root/'cyclic.iso';data=bytearray(iso.read_bytes()[:131072]);sector=struct.unpack_from('<I',data,0x10014)[0]
struct.pack_into('<H',data,sector*2048,1);struct.pack_into('<H',data,sector*2048+4,1);bad.write_bytes(data)
r=subprocess.run([exe,'list',str(bad)],capture_output=True,text=True)
same(r.returncode,1,'malformed directory rejected')

if a.exiso:
    external=root/'synthetic-exiso'
    r=subprocess.run([str(a.exiso),'-q','-d',str(external),'-x',str(iso)],capture_output=True,text=True)
    if r.returncode: raise RuntimeError(r.stdout+r.stderr)
    same(tree(src),tree(external),'original Exiso extracts new ISO with identical files')

if a.game:
    run('inspect',a.game); run('verify-god',a.game)
    original_manifest=run('manifest',a.game)
    (root/'original-manifest.tsv').write_text(original_manifest)
    extracted=root/'l4d2-extracted';run('extract',a.game,extracted)
    reference=tree(extracted)
    originaliso=root/'l4d2-original.iso';run('iso',a.game,originaliso)
    same(run('manifest',originaliso),original_manifest,'original GOD to ISO preserves every file')
    rebuilt=root/'l4d2-rebuilt.iso';run('iso',extracted,rebuilt)
    # Manifests are tree traversal order dependent; compare normalized lines.
    same(sorted(run('manifest',rebuilt).splitlines()),sorted(original_manifest.splitlines()),'rebuilt ISO preserves every file')
    if a.exiso:
        oracle=root/'l4d2-exiso'
        r=subprocess.run([str(a.exiso),'-q','-d',str(oracle),'-x',str(rebuilt)],capture_output=True,text=True)
        if r.returncode: raise RuntimeError(r.stdout+r.stderr)
        same(reference,tree(oracle),'original Exiso reads rebuilt Left 4 Dead 2 ISO')
    rebuiltgod=root/'l4d2-rebuilt-god';run('god',rebuilt,rebuiltgod,'--title','Left 4 Dead 2');newpkg=package(rebuiltgod);run('verify-god',newpkg)
    back=root/'l4d2-roundtrip.iso';run('iso',newpkg,back);same(digest(rebuilt),digest(back),'Left 4 Dead 2 ISO GOD ISO is byte identical')
    reextract=root/'l4d2-god-extracted';run('extract',newpkg,reextract);same(reference,tree(reextract),'Left 4 Dead 2 GOD round trip preserves all 96 files')
    foldergod=root/'l4d2-folder-god';run('god',extracted,foldergod,'--title','Left 4 Dead 2');run('verify-god',package(foldergod))
    same(sorted(run('manifest',package(foldergod)).splitlines()),sorted(original_manifest.splitlines()),'Left 4 Dead 2 extracted folder to GOD preserves every file')
    dlc=a.game.parent.parent/'00000002'
    for f in sorted(dlc.iterdir()):
        if f.is_file():
            run('list-dlc',f);out=root/('dlc-'+f.name);run('extract-dlc',f,out)
            same(len(tree(out))>0,True,'DLC extracted '+f.name)

print('ALL CHECKS PASSED',root/'validation.json',flush=True)
