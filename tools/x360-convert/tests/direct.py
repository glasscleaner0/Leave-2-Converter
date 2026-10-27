"""Regression checks for direct folder-to-GOD without an intermediate ISO."""
import argparse,hashlib,json,pathlib,subprocess,time
p=argparse.ArgumentParser();p.add_argument('--exe',required=True,type=pathlib.Path);p.add_argument('--baseline',required=True,type=pathlib.Path);p.add_argument('--fixtures',required=True,type=pathlib.Path);p.add_argument('--work',required=True,type=pathlib.Path);p.add_argument('--game',action='store_true');a=p.parse_args()
a.work.mkdir(parents=True,exist_ok=False);checks=[]
def save(): (a.work/'direct-validation.json').write_text(json.dumps(checks,indent=2))
def call(exe,*args,success=True):
 start=time.monotonic();r=subprocess.run([str(exe),*map(str,args)],capture_output=True,text=True,encoding='utf8',errors='replace')
 checks.append(dict(command=[str(exe),*map(str,args)],exit=r.returncode,seconds=round(time.monotonic()-start,3),stdout=r.stdout,stderr=r.stderr));save()
 assert (r.returncode==0)==success,r.stderr
 print('PASS',args[0],*(str(x)for x in args[1:3]),flush=True);return r
def digest(p):
 with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def tree(p):return {str(f.relative_to(p)).replace('\\','/'):(f.stat().st_size,digest(f))for f in p.rglob('*')if f.is_file()}
def same(x,y,label):
 assert x==y,label;checks.append(dict(check=label,passed=True));save();print('PASS',label,flush=True)
def pkg(p):return next(f for f in p.iterdir()if f.is_file())
def scenario(name,source,title,reference=None):
 out=a.work/(name+'-direct')
 # This path formerly had to be available for creating an ISO. A directory
 # with a sentinel makes it impossible for the old implementation to proceed.
 sentinel=pathlib.Path(str(out)+'.building.iso');sentinel.mkdir();(sentinel/'untouched.txt').write_text('must remain untouched')
 result=call(a.exe,'god',source,out,'--title',title)
 stages={line.split('\t')[1]for line in result.stderr.splitlines()if line.startswith('progress\t')}
 same(stages,{'god'},name+': single god progress stage')
 same((sentinel/'untouched.txt').read_text(),'must remain untouched',name+': old intermediate path not used')
 if reference is None:
  iso=a.work/(name+'-reference.iso');call(a.baseline,'iso',source,iso,'--quiet')
  reference=a.work/(name+'-reference-god');call(a.baseline,'god',iso,reference,'--title',title,'--quiet')
 same(tree(out),tree(reference),name+': entire GOD package byte-identical to previous two-step output')
 call(a.exe,'verify-god',pkg(out),'--quiet')
 extracted=a.work/(name+'-extracted');call(a.exe,'extract',pkg(out),extracted,'--quiet')
 same(tree(source),tree(extracted),name+': extraction preserves every source file')
 call(a.exe,'god',source,out,'--title',title,success=False)
 same(tree(out),tree(reference),name+': refusing existing output leaves it unchanged')
 return out
synthetic=a.fixtures/'synthetic';scenario('synthetic',synthetic,'Integration test')
# Missing title metadata should fail before creating output or touching the old
# temporary location; --title-id still works without a default.xex.
missing=a.work/'no-title';missing.mkdir();(missing/'empty').write_bytes(b'')
failed=a.work/'missing-title-output';call(a.exe,'god',missing,failed,success=False)
same(failed.exists(),False,'metadata failure creates no output')
override=a.work/'explicit-title';call(a.exe,'god',missing,override,'--title-id','454108D4','--quiet');call(a.exe,'verify-god',pkg(override),'--quiet')
if a.game:
 source=a.fixtures/'l4d2-extracted';reference=a.fixtures/'l4d2-folder-god'
 out=scenario('l4d2',source,'Left 4 Dead 2',reference)
 restored=a.work/'l4d2-recovered.iso';call(a.exe,'iso',pkg(out),restored,'--quiet')
 same(digest(restored),digest(a.fixtures/'l4d2-rebuilt.iso'),'Left 4 Dead 2 GOD exports the exact previous rebuilt ISO')
 print('GAME FILES',len(tree(source)),flush=True)
print('ALL DIRECT CONVERSION CHECKS PASSED',flush=True)
