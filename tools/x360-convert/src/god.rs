use crate::{
    Result, bad, be32, disc,
    hash::{hex, sha1},
    progress,
    volume::{PAYLOAD, Volume},
};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Seek, SeekFrom, Write},
    path::Path,
};
fn put32(h: &mut [u8], p: usize, n: u32) {
    h[p..p + 4].copy_from_slice(&n.to_be_bytes());
}
fn put64(h: &mut [u8], p: usize, n: u64) {
    h[p..p + 8].copy_from_slice(&n.to_be_bytes());
}
fn text(h: &mut [u8], p: usize, s: &str) {
    for (i, c) in s.encode_utf16().take(63).enumerate() {
        h[p + i * 2..p + i * 2 + 2].copy_from_slice(&c.to_be_bytes());
    }
}
pub fn to_iso(v: &mut Volume, out: &Path) -> Result<()> {
    disc::entries(v)?;
    let mut f = OpenOptions::new().write(true).create_new(true).open(out)?;
    let mut buf = vec![0; 1024 * 1024];
    let mut pos = 0;
    let total = v.len();
    while pos < total {
        let n = (total - pos).min(buf.len() as u64) as usize;
        v.read_at(pos, &mut buf[..n])?;
        f.write_all(&buf[..n])?;
        pos += n as u64;
        progress("iso", pos, total);
    }
    f.sync_all()?;
    Ok(())
}
pub fn build(input: &Path, out: &Path, title: &str, title_override: Option<u32>) -> Result<()> {
    let mut v = if input.is_dir() {
        Volume::Folder(disc::FolderVolume::open(input)?)
    } else {
        Volume::open(input)?
    };
    let es = disc::entries(&mut v)?;
    let xex = es
        .iter()
        .find(|e| e.path.eq_ignore_ascii_case("default.xex") && !e.dir);
    let mut exec = [0u8; 24];
    if let Some(e) = xex {
        let head = v.bytes(e.sector as u64 * 2048, (e.size as usize).min(1024 * 1024))?;
        if head.len() >= 24 && &head[..4] == b"XEX2" {
            let count = be32(&head, 20) as usize;
            if count > 4096 || 24 + count * 8 > head.len() {
                return bad("Invalid XEX optional headers");
            }
            for i in 0..count {
                let p = 24 + i * 8;
                if be32(&head, p) == 0x40006 {
                    let off = be32(&head, p + 4) as usize;
                    if off + 24 > head.len() {
                        return bad("XEX execution ID out of range");
                    }
                    exec.copy_from_slice(&head[off..off + 24]);
                }
            }
        }
    }
    if let Some(id) = title_override {
        exec[12..16].copy_from_slice(&id.to_be_bytes());
    }
    if exec[12..16] == [0; 4] {
        return bad("No title ID found in default.xex; supply --title-id HEX");
    }
    let total = v.len().div_ceil(4096) * 4096;
    let blocks = total / 4096;
    if blocks > 0xffffff {
        return bad("GOD data exceeds 24-bit block count");
    }
    let count = total.div_ceil(PAYLOAD);
    let mut h = vec![0u8; 0xb000];
    h[..4].copy_from_slice(b"LIVE");
    h[0x22c..0x234].fill(255);
    put32(&mut h, 0x340, 0xad0e);
    put32(&mut h, 0x344, 0x7000);
    put32(&mut h, 0x348, 2);
    put64(&mut h, 0x34c, total);
    h[0x354..0x36c].copy_from_slice(&exec);
    h[0x379] = 0x24;
    h[0x37a] = 5;
    h[0x37b] = 5;
    h[0x37c] = 0x11;
    h[0x392..0x395].copy_from_slice(&(blocks as u32).to_be_bytes()[1..]);
    put32(&mut h, 0x39d, count as u32);
    put32(&mut h, 0x3a9, 1);
    for locale in 0..9 {
        text(&mut h, 0x411 + locale * 128, title);
        text(&mut h, 0xd11 + locale * 128, title);
    }
    text(&mut h, 0x1691, title);
    fs::create_dir(out)?;
    let data = out.join("payload.data");
    fs::create_dir(&data)?;
    let mut combined = 0;
    let mut pos = 0;
    for file_index in 0..count {
        let remaining = (total - pos).min(PAYLOAD);
        let groups = remaining.div_ceil(0xcc000);
        let mut f = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(data.join(format!("Data{file_index:04}")))?;
        let mut master = [0u8; 4096];
        f.write_all(&master)?;
        for group in 0..groups {
            let bytes = (remaining - group * 0xcc000).min(0xcc000) as usize;
            let mut payload = vec![0u8; bytes];
            let n = (v.len() - pos.min(v.len())).min(bytes as u64) as usize;
            if n > 0 {
                v.read_at(pos, &mut payload[..n])?;
            }
            let mut table = [0u8; 4096];
            for (i, b) in payload.chunks_exact(4096).enumerate() {
                table[i * 20..i * 20 + 20].copy_from_slice(&sha1(b));
            }
            master[group as usize * 20..group as usize * 20 + 20].copy_from_slice(&sha1(&table));
            f.write_all(&table)?;
            f.write_all(&payload)?;
            pos += bytes as u64;
            progress("god", pos, total);
        }
        f.seek(SeekFrom::Start(0))?;
        f.write_all(&master)?;
        f.sync_all()?;
        combined += f.metadata()?.len();
    }
    // Chain master tables backwards: the final slot authenticates the next fragment.
    let mut next = [0u8; 20];
    for i in (0..count).rev() {
        let mut f = OpenOptions::new()
            .read(true)
            .write(true)
            .open(data.join(format!("Data{i:04}")))?;
        let mut master = [0; 4096];
        f.read_exact(&mut master)?;
        master[0xfdc..0xff0].copy_from_slice(&next);
        next = sha1(&master);
        f.seek(SeekFrom::Start(0))?;
        f.write_all(&master)?;
        f.sync_all()?;
    }
    h[0x37d..0x391].copy_from_slice(&next);
    put64(&mut h, 0x3a1, combined);
    let header_hash = sha1(&h[0x344..]);
    h[0x32c..0x340].copy_from_slice(&header_hash);
    let name = hex(&header_hash[..10]).to_uppercase();
    fs::rename(&data, out.join(format!("{name}.data")))?;
    let mut f = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(out.join(&name))?;
    f.write_all(&h)?;
    f.sync_all()?;
    println!("package\t{}", out.join(name).display());
    Ok(())
}
pub fn verify(input: &Path) -> Result<()> {
    let crate::volume::Volume::God(g) = Volume::open(input)? else {
        return bad("verify-god requires a GOD package");
    };
    let folder = std::path::PathBuf::from(format!("{}.data", input.display()));
    let count = be32(&g.header, 0x39d);
    let mut expected: [u8; 20] = g.header[0x37d..0x391].try_into()?;
    let mut bytes = 0;
    for i in 0..count {
        let mut f = File::open(folder.join(format!("Data{i:04}")))?;
        let length = f.metadata()?.len();
        let mut master = [0; 4096];
        f.read_exact(&mut master)?;
        if sha1(&master) != expected {
            return bad(format!("Master hash mismatch: Data{i:04}"));
        }
        expected.copy_from_slice(&master[0xfdc..0xff0]);
        let mut p = 4096;
        let mut group = 0;
        while p < length {
            let mut table = [0; 4096];
            f.read_exact(&mut table)?;
            p += 4096;
            if sha1(&table) != master[group * 20..group * 20 + 20] {
                return bad(format!("Hash table mismatch: Data{i:04}, group {group}"));
            }
            let blocks = ((length - p) / 4096).min(204) as usize;
            for b in 0..blocks {
                let mut block = [0; 4096];
                f.read_exact(&mut block)?;
                if sha1(&block) != table[b * 20..b * 20 + 20] {
                    return bad(format!(
                        "Data hash mismatch: Data{i:04}, group {group}, block {b}"
                    ));
                }
                p += 4096;
                bytes += 4096;
            }
            group += 1;
            progress("verify", bytes, g.raw_len);
        }
    }
    if expected != [0; 20] {
        return bad("Last GOD fragment has a nonzero next-fragment hash");
    }
    let size = be32(&g.header, 0x340) as usize;
    let aligned = size.div_ceil(4096) * 4096;
    if aligned > g.header.len() || sha1(&g.header[0x344..aligned]) != g.header[0x32c..0x340] {
        return bad("GOD metadata header hash mismatch");
    }
    println!("verified\t{count}\t{bytes}");
    Ok(())
}
