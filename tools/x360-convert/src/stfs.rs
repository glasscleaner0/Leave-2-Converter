// Read-only STFS support for separate LIVE/PIRS DLC packages.
use crate::{Result, bad, be32, disc::safe_name, hash::sha1, progress};
use std::{
    collections::HashSet,
    fs::{self, File, OpenOptions},
    io::{Read, Seek, SeekFrom, Write},
    path::Path,
};
fn le24(b: &[u8], p: usize) -> u32 {
    b[p] as u32 | ((b[p + 1] as u32) << 8) | ((b[p + 2] as u32) << 16)
}
fn be24(b: &[u8], p: usize) -> u32 {
    ((b[p] as u32) << 16) | ((b[p + 1] as u32) << 8) | b[p + 2] as u32
}
struct Record {
    name: String,
    parent: u16,
    block: u32,
    size: u32,
    dir: bool,
    consecutive: bool,
}
pub struct Package {
    f: File,
    base: u64,
    length: u64,
    records: Vec<Option<Record>>,
}
impl Package {
    pub fn open(p: &Path) -> Result<Self> {
        let mut f = File::open(p)?;
        let length = f.metadata()?.len();
        let mut h = vec![0; 0x400];
        f.read_exact(&mut h)?;
        if ![b"LIVE".as_slice(), b"PIRS"].contains(&&h[..4]) || be32(&h, 0x3a9) != 0 {
            return bad("DLC extraction supports LIVE/PIRS STFS packages");
        }
        let base = (be32(&h, 0x340) as u64).div_ceil(4096) * 4096;
        if base < 0x1000 || base >= length || h[0x379] != 0x24 {
            return bad("Invalid STFS descriptor");
        }
        // LIVE/PIRS have one hash table at each level.
        let count = u16::from_le_bytes(h[0x37c..0x37e].try_into()?) as usize;
        let mut block = le24(&h, 0x37e);
        if count == 0 || count > 65535 {
            return bad("Invalid STFS file table count");
        }
        let mut pkg = Self {
            f,
            base,
            length,
            records: Vec::new(),
        };
        let mut visited = HashSet::new();
        for i in 0..count {
            if !visited.insert(block) {
                return bad("Cyclic STFS file table");
            }
            let mut table = [0u8; 4096];
            pkg.read_block(block, &mut table)?;
            for r in table.chunks_exact(64) {
                let n = (r[40] & 63) as usize;
                if n == 0 {
                    pkg.records.push(None);
                    continue;
                }
                if n > 40 {
                    return bad("Invalid STFS file name length");
                }
                let name = std::str::from_utf8(&r[..n])?.to_string();
                if !safe_name(&name) {
                    return bad("Unsafe STFS name");
                }
                pkg.records.push(Some(Record {
                    name,
                    parent: u16::from_be_bytes(r[50..52].try_into()?),
                    block: le24(r, 47),
                    size: be32(r, 52),
                    dir: r[40] & 128 != 0,
                    consecutive: r[40] & 64 != 0,
                }));
            }
            if i + 1 < count {
                block = pkg.next(block)?;
            }
        }
        let mut names = HashSet::new();
        for i in 0..pkg.records.len() {
            if pkg.records[i].is_some() {
                let name = pkg.path(i, &mut HashSet::new())?;
                if !names.insert(name.to_ascii_lowercase()) {
                    return bad("Duplicate STFS path");
                }
            }
        }
        Ok(pkg)
    }
    fn offset(&self, b: u32) -> Result<u64> {
        if b >= 0xffffff {
            return bad("STFS block is out of range");
        }
        let b = b as u64;
        let physical = b
            + b / 170
            + 1
            + if b >= 170 { b / 28900 + 1 } else { 0 }
            + if b >= 28900 { b / 4913000 + 1 } else { 0 };
        let p = self.base + physical * 4096;
        if p + 4096 > self.length {
            return bad("STFS extent exceeds package length");
        }
        Ok(p)
    }
    fn read_block(&mut self, b: u32, out: &mut [u8; 4096]) -> Result<()> {
        let p = self.offset(b)?;
        self.f.seek(SeekFrom::Start(p))?;
        self.f.read_exact(out)?;
        let table = self.offset(b / 170 * 170)? - 4096;
        self.f
            .seek(SeekFrom::Start(table + (b % 170) as u64 * 24))?;
        let mut expected = [0u8; 20];
        self.f.read_exact(&mut expected)?;
        if sha1(out) != expected {
            return bad(format!("STFS data hash mismatch at block {b}"));
        }
        Ok(())
    }
    fn next(&mut self, b: u32) -> Result<u32> {
        let group = b / 170 * 170;
        let table = self.offset(group)? - 4096;
        self.f
            .seek(SeekFrom::Start(table + (b % 170) as u64 * 24 + 21))?;
        let mut n = [0u8; 3];
        self.f.read_exact(&mut n)?;
        Ok(be24(&n, 0))
    }
    fn path(&self, i: usize, visited: &mut HashSet<usize>) -> Result<String> {
        if visited.len() > 128 || !visited.insert(i) {
            return bad("STFS parent cycle");
        }
        let r = self
            .records
            .get(i)
            .and_then(|r| r.as_ref())
            .ok_or("Invalid STFS parent entry")?;
        if r.parent == 65535 {
            Ok(r.name.clone())
        } else {
            let parent = self
                .records
                .get(r.parent as usize)
                .and_then(|r| r.as_ref())
                .ok_or("Missing STFS parent")?;
            if !parent.dir {
                return bad("STFS parent is a file");
            }
            Ok(format!(
                "{}/{}",
                self.path(r.parent as usize, visited)?,
                r.name
            ))
        }
    }
    pub fn list(&self) -> Result<()> {
        for (i, r) in self.records.iter().enumerate() {
            if let Some(r) = r {
                println!(
                    "{}\t{}\t{}",
                    if r.dir { "dir" } else { "file" },
                    r.size,
                    self.path(i, &mut HashSet::new())?
                );
            }
        }
        Ok(())
    }
    pub fn extract(&mut self, out: &Path) -> Result<()> {
        fs::create_dir(out)?;
        let total: u64 = self
            .records
            .iter()
            .flatten()
            .filter(|r| !r.dir)
            .map(|r| r.size as u64)
            .sum();
        let mut done = 0;
        for i in 0..self.records.len() {
            let Some(r) = &self.records[i] else {
                continue;
            };
            let p = out.join(self.path(i, &mut HashSet::new())?);
            let (dir, consecutive, size, mut block) = (r.dir, r.consecutive, r.size, r.block);
            if dir {
                fs::create_dir_all(p)?;
                continue;
            }
            fs::create_dir_all(p.parent().unwrap())?;
            let mut f = OpenOptions::new().write(true).create_new(true).open(p)?;
            let mut remaining = size as u64;
            let mut visited = HashSet::new();
            while remaining > 0 {
                if !visited.insert(block) {
                    return bad("STFS file chain cycle");
                }
                let mut data = [0; 4096];
                self.read_block(block, &mut data)?;
                let n = remaining.min(4096) as usize;
                f.write_all(&data[..n])?;
                remaining -= n as u64;
                done += n as u64;
                progress("dlc", done, total);
                if remaining > 0 {
                    block = if consecutive {
                        block + 1
                    } else {
                        self.next(block)?
                    };
                }
            }
        }
        Ok(())
    }
}
