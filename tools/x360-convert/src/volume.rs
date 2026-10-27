use crate::{Result, bad, be32};
use std::{
    fs::{self, File},
    io::{Read, Seek, SeekFrom},
    path::{Path, PathBuf},
};
pub const SECTOR: u64 = 2048;
pub const MAGIC: &[u8; 20] = b"MICROSOFT*XBOX*MEDIA";
pub const PAYLOAD: u64 = 0xa1c4 * 4096;
pub const FRAGMENT: u64 = 0xa290000;
pub struct God {
    pub header: Vec<u8>,
    files: Vec<File>,
    sizes: Vec<u64>,
    pub enhanced: bool,
    start: u64,
    pub raw_len: u64,
}
impl God {
    pub fn open(p: &Path) -> Result<Self> {
        let h = fs::read(p)?;
        if h.len() < 0x400
            || ![b"LIVE".as_slice(), b"PIRS", b"CON "].contains(&&h[..4])
            || be32(&h, 0x3a9) != 1
        {
            return bad("Not an SVOD/GOD package");
        }
        let count = be32(&h, 0x39d) as usize;
        if count == 0 || count > 10000 {
            return bad("Unsupported GOD fragment count");
        }
        let folder = PathBuf::from(format!("{}.data", p.display()));
        let mut files = Vec::new();
        let mut sizes = Vec::new();
        let mut raw_len = 0;
        for i in 0..count {
            let f = File::open(folder.join(format!("Data{i:04}")))?;
            let n = f.metadata()?.len();
            if n < 8192 || n > FRAGMENT || n % 4096 != 0 || (i + 1 < count && n != FRAGMENT) {
                return bad("Invalid GOD fragment length");
            }
            let groups = (n - 4096).div_ceil(0xcd000);
            raw_len += n - 4096 - groups * 4096;
            files.push(f);
            sizes.push(n);
        }
        let start = ((h[0x395] as u64) << 16) | ((h[0x396] as u64) << 8) | h[0x397] as u64;
        let enhanced = h[0x391] & 0x40 != 0;
        let mut g = Self {
            header: h,
            files,
            sizes,
            enhanced,
            start,
            raw_len,
        };
        let mut sig = [0u8; 20];
        g.raw_read(if enhanced { 0 } else { 0x10000 }, &mut sig)?;
        if sig != *MAGIC {
            return bad("Unsupported GOD layout: volume descriptor not found");
        }
        Ok(g)
    }
    pub fn raw_read(&mut self, mut offset: u64, mut buf: &mut [u8]) -> Result<()> {
        while !buf.is_empty() {
            let file = (offset / PAYLOAD) as usize;
            let inner = offset % PAYLOAD;
            let pos = 8192 + inner + (inner / 0xcc000) * 4096;
            let n = (0xcc000 - inner % 0xcc000).min(buf.len() as u64) as usize;
            if file >= self.files.len() || pos + n as u64 > self.sizes[file] {
                return bad("GOD read extends past its data");
            }
            self.files[file].seek(SeekFrom::Start(pos))?;
            self.files[file].read_exact(&mut buf[..n])?;
            offset += n as u64;
            buf = &mut buf[n..];
        }
        Ok(())
    }
    pub fn len(&self) -> u64 {
        self.raw_len + self.start * 4096 - if self.enhanced { 4096 } else { 0 }
    }
    pub fn read_at(&mut self, mut offset: u64, mut b: &mut [u8]) -> Result<()> {
        if self.enhanced && offset < 0x10800 {
            if offset < 0x10000 {
                let n = (0x10000 - offset).min(b.len() as u64) as usize;
                b[..n].fill(0);
                offset += n as u64;
                b = &mut b[n..];
            }
            if !b.is_empty() && offset < 0x10800 {
                let n = (0x10800 - offset).min(b.len() as u64) as usize;
                self.raw_read(offset - 0x10000, &mut b[..n])?;
                offset += n as u64;
                b = &mut b[n..];
            }
        }
        if b.is_empty() {
            return Ok(());
        }
        let adjusted = offset
            .checked_add(if self.enhanced { 4096 } else { 0 })
            .and_then(|x| x.checked_sub(self.start * 4096))
            .ok_or("Sector precedes stored GOD data")?;
        self.raw_read(adjusted, b)
    }
}
pub enum Volume {
    Iso { file: File, base: u64, len: u64 },
    God(God),
    Folder(crate::disc::FolderVolume),
}
impl Volume {
    pub fn open(p: &Path) -> Result<Self> {
        let mut f = File::open(p)?;
        let len = f.metadata()?.len();
        let mut sig = [0; 4];
        f.read_exact(&mut sig)?;
        if [b"LIVE".as_slice(), b"PIRS", b"CON "].contains(&sig.as_slice()) {
            return Ok(Self::God(God::open(p)?));
        }
        for base in [0, 0xfd90000, 0x2080000, 0x18300000] {
            if base + 0x10800 > len {
                continue;
            }
            f.seek(SeekFrom::Start(base + 0x10000))?;
            let mut m = [0; 20];
            f.read_exact(&mut m)?;
            if m == *MAGIC {
                return Ok(Self::Iso {
                    file: f,
                    base,
                    len: len - base,
                });
            }
        }
        bad("No Xbox volume descriptor found at known disc partition offsets")
    }
    pub fn len(&self) -> u64 {
        match self {
            Self::Iso { len, .. } => *len,
            Self::God(g) => g.len(),
            Self::Folder(folder) => folder.len(),
        }
    }
    pub fn read_at(&mut self, offset: u64, b: &mut [u8]) -> Result<()> {
        if offset
            .checked_add(b.len() as u64)
            .is_none_or(|n| n > self.len())
        {
            return bad("Volume read out of bounds");
        }
        match self {
            Self::Iso { file, base, .. } => {
                file.seek(SeekFrom::Start(*base + offset))?;
                file.read_exact(b)?;
                Ok(())
            }
            Self::God(g) => g.read_at(offset, b),
            Self::Folder(folder) => folder.read_at(offset, b),
        }
    }
    pub fn bytes(&mut self, offset: u64, n: usize) -> Result<Vec<u8>> {
        let mut b = vec![0; n];
        self.read_at(offset, &mut b)?;
        Ok(b)
    }
}
