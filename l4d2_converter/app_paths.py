"""Portable application paths for source and frozen Windows releases."""
from pathlib import Path
import sys,json,hashlib

def application_home():
    return Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]

def source_fingerprint():
    root=application_home()
    if getattr(sys,'frozen',False):
        return json.loads((root/'BUILD-INFO.json').read_text(encoding='utf-8'))['converter_source_sha256']
    return hashlib.sha256(b''.join(p.relative_to(root).as_posix().encode()+b'\0'+p.read_bytes()
        for p in sorted(root.rglob('*.py')) if not {'__pycache__','.build','dist'} & set(p.relative_to(root).parts))).hexdigest()
