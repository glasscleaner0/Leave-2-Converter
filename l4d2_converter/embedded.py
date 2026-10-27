"""Recover embedded textures omitted by the external BSP conversion job."""
import hashlib
import struct
from .archive import XboxZip, aligned_zip
from .formats import bsp_lump, unpack_source, validate_asset
from .textures import texture_info


def missing_embedded_textures(source, console):
    original = XboxZip(bsp_lump(source, 40) or aligned_zip({}))
    converted = XboxZip(bsp_lump(console, 40) or aligned_zip({}))
    return {name:original.read(name) for name in sorted(original.entries)
            if name.startswith('materials/') and name.endswith('.vtf') and '.360.' not in name
            and name[:-4]+'.360.vtf' not in converted.entries}


def recover_embedded_textures(source, console, backend):
    additions, records = {}, []
    for name, payload in missing_embedded_textures(source, console).items():
        plain = unpack_source(payload)
        if len(plain)<64 or plain[:4]!=b'VTF\0':
            raise ValueError('Invalid omitted embedded PC texture: '+name)
        flags = struct.unpack_from('<I',plain,20)[0]
        frames = struct.unpack_from('<H',plain,24)[0]
        alias='materials/__converter_input/embedded_'+hashlib.sha256(name.encode()).hexdigest()[:16]+'.vtf'
        target=name[:-4]+'.360.vtf'
        expected=alias[:-4]+'.360.vtf'
        path=backend.game/alias
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(payload)
        try:
            result=backend.run(alias,[expected])
            if not result:
                raise ValueError('SDK omitted embedded texture and individual conversion failed: '+name)
            data=result[expected]
            validate_asset(target,data)
            info=texture_info(data)
            if bool(info['flags'] & 0x4000)!=bool(flags & 0x4000) or info['frames']!=frames:
                raise ValueError('Recovered texture changed cubemap/frame semantics: '+name)
            additions[target]=data
            records.append({'source':name,'output':target,'reason':'SDK BSP conversion omitted source texture',
                            'method':'individual_external_sdk_conversion','cubemap':bool(flags & 0x4000),
                            'frames':frames,'hardware_tested':False})
        finally:
            path.unlink(missing_ok=True)
            (backend.game/expected).unlink(missing_ok=True)
    return additions, records
