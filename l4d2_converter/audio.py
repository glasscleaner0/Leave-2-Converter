"""Optional user-supplied decoder for WAV encodings rejected by the old SDK."""
from pathlib import Path
import hashlib
import os
import shutil
import struct
import subprocess
import wave
from .formats import pcm_xwv


def fallback_xwv(source, scratch, decoder='', timeout=120):
    source=Path(source)
    data=source.read_bytes()
    try:
        return pcm_xwv(data),{'method':'pcm_xwv','source_samples_preserved':True}
    except (ValueError,EOFError,wave.Error) as original:
        # wave.Error is not a ValueError. The native format check above is the
        # first choice; an external decoder is only a fallback, never bundled.
        reason=str(original)
    executable=decoder or shutil.which('ffmpeg')
    if not executable:
        raise ValueError(reason+'; this WAV needs a user-supplied FFmpeg decoder')
    executable=Path(executable).resolve()
    if not executable.is_file(): raise ValueError('Audio decoder executable does not exist')
    riff=data[:4]==b'RIFF' and data[8:12]==b'WAVE'
    mpeg=data[:3]==b'ID3' or (len(data)>1 and data[0]==255 and data[1]&0xe0==0xe0)
    if not riff and not mpeg: raise ValueError('Expected RIFF WAVE or MPEG audio in this .wav source')
    pos=12
    while riff and pos+8<=len(data):
        tag,size=struct.unpack_from('<4sI',data,pos)
        if pos+8+size>len(data): raise ValueError('Truncated WAV chunk')
        if tag==b'smpl':
            if size<36: raise ValueError('Invalid WAV sampler chunk')
            if struct.unpack_from('<I',data,pos+8+28)[0]:
                raise ValueError('Decoder fallback cannot silently discard WAV sample-loop metadata')
        pos+=8+size+size%2
    scratch=Path(scratch);scratch.mkdir(parents=True,exist_ok=True)
    target=scratch/(hashlib.sha256(data).hexdigest()+'.wav')
    target.unlink(missing_ok=True)
    result=subprocess.run([str(executable),'-v','error','-nostdin','-y','-i',str(source),
        '-ar','44100','-c:a','pcm_s16le',str(target)],capture_output=True,timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if result.returncode or not target.is_file():
        raise ValueError('Audio decoder failed: '+result.stderr.decode(errors='replace')[-500:])
    output=pcm_xwv(target.read_bytes())
    return output,{'method':'external_ffmpeg_pcm','decoder':str(executable),
        'decoder_sha256':hashlib.sha256(executable.read_bytes()).hexdigest(),
        'source_samples_preserved':False,'output_sample_rate':44100,'output_bits':16,
        'note':'Decoded/resampled to supported PCM. This is not a byte-preserving audio transformation.'}
