use crate::{
    Result, bad,
    hash::{Sha1, hex},
    le32, progress,
    volume::{MAGIC, SECTOR, Volume},
};
use std::{
    collections::{BTreeSet, HashSet},
    fs::{self, File, OpenOptions},
    io::{Read, Seek, SeekFrom, Write},
    path::{Path, PathBuf},
};
#[derive(Debug, Clone)]
pub struct Entry {
    pub path: String,
    pub sector: u32,
    pub size: u32,
    pub dir: bool,
}
pub fn safe_name(n: &str) -> bool {
    if n.is_empty()
        || n == "."
        || n == ".."
        || n.ends_with(['.', ' '])
        || n.chars().any(|c| c < ' ' || "<>:\"/\\|?*".contains(c))
    {
        return false;
    }
    let stem = n.split('.').next().unwrap().to_ascii_uppercase();
    ![
        "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8",
        "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    ]
    .contains(&stem.as_str())
}
pub fn entries(v: &mut Volume) -> Result<Vec<Entry>> {
    let d = v.bytes(0x10000, 2048)?;
    if &d[..20] != MAGIC || &d[2028..] != MAGIC {
        return bad("Invalid Xbox volume descriptor");
    }
    let mut out = Vec::new();
    let mut dirs = HashSet::new();
    visit_dir(v, le32(&d, 20), le32(&d, 24), "", 0, &mut dirs, &mut out)?;
    Ok(out)
}
fn visit_dir(
    v: &mut Volume,
    sector: u32,
    size: u32,
    prefix: &str,
    depth: usize,
    dirs: &mut HashSet<(u32, u32)>,
    out: &mut Vec<Entry>,
) -> Result<()> {
    if size == 0 {
        return Ok(());
    }
    if depth > 128 || size > 64 * 1024 * 1024 || !dirs.insert((sector, size)) {
        return bad("Cyclic or excessive directory table");
    }
    let table = v.bytes(sector as u64 * SECTOR, size as usize)?;
    let mut stack = vec![0usize];
    let mut seen = HashSet::new();
    let mut names = BTreeSet::new();
    let mut sub = Vec::new();
    while let Some(pos) = stack.pop() {
        if !seen.insert(pos) || pos + 14 > table.len() {
            return bad("Invalid or cyclic directory entry");
        }
        if table[pos..pos + 4] == [255; 4] {
            continue;
        }
        let n = table[pos + 13] as usize;
        if pos + 14 + n > table.len() {
            return bad("Truncated directory name");
        }
        let name = std::str::from_utf8(&table[pos + 14..pos + 14 + n])
            .map_err(|_| "Non-UTF-8 Xbox name is unsupported")?;
        if !safe_name(name) || !names.insert(name.to_ascii_lowercase()) {
            return bad("Unsafe or duplicate file name");
        }
        let path = if prefix.is_empty() {
            name.to_string()
        } else {
            format!("{prefix}/{name}")
        };
        let e = Entry {
            path,
            sector: le32(&table, pos + 4),
            size: le32(&table, pos + 8),
            dir: table[pos + 12] & 0x10 != 0,
        };
        if e.sector as u64 * SECTOR + e.size as u64 > v.len() {
            return bad("File extent exceeds the volume");
        }
        if e.dir {
            sub.push(e.clone());
        }
        out.push(e);
        for p in [pos, pos + 2] {
            let link = u16::from_le_bytes(table[p..p + 2].try_into().unwrap()) as usize * 4;
            if link != 0 {
                stack.push(link);
            }
        }
        if out.len() > 1_000_000 {
            return bad("Too many directory entries");
        }
    }
    for e in sub {
        visit_dir(v, e.sector, e.size, &e.path, depth + 1, dirs, out)?;
    }
    Ok(())
}
pub fn extract(v: &mut Volume, out: &Path) -> Result<()> {
    let es = entries(v)?;
    fs::create_dir(out)?;
    let total: u64 = es.iter().filter(|e| !e.dir).map(|e| e.size as u64).sum();
    let mut done = 0;
    let mut buf = vec![0; 1024 * 1024];
    for e in es {
        let p = out.join(&e.path);
        if e.dir {
            fs::create_dir_all(p)?;
            continue;
        }
        if let Some(parent) = p.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut f = OpenOptions::new().write(true).create_new(true).open(p)?;
        let mut off = 0;
        while off < e.size as u64 {
            let n = (e.size as u64 - off).min(buf.len() as u64) as usize;
            v.read_at(e.sector as u64 * SECTOR + off, &mut buf[..n])?;
            f.write_all(&buf[..n])?;
            off += n as u64;
            done += n as u64;
            progress("extract", done, total);
        }
    }
    Ok(())
}
pub fn manifest(v: &mut Volume) -> Result<()> {
    let es = entries(v)?;
    let mut buf = vec![0; 1024 * 1024];
    for e in es.into_iter().filter(|e| !e.dir) {
        let mut h = Sha1::new();
        let mut off = 0;
        while off < e.size as u64 {
            let n = (e.size as u64 - off).min(buf.len() as u64) as usize;
            v.read_at(e.sector as u64 * SECTOR + off, &mut buf[..n])?;
            h.update(&buf[..n]);
            off += n as u64;
        }
        println!("{}\t{}\t{}", hex(&h.finish()), e.size, e.path);
    }
    Ok(())
}
struct Node {
    name: String,
    path: PathBuf,
    size: u32,
    sector: u32,
    children: Option<Vec<Node>>,
    table: Vec<u8>,
}

enum ExtentData {
    Bytes(Vec<u8>),
    File(PathBuf),
}

struct Extent {
    start: u64,
    len: u64,
    data: ExtentData,
}

/// A seekable disc layout backed by source files rather than an intermediate ISO.
/// Only directory tables and the volume descriptor are kept in memory. Gaps and
/// sector padding read as zero, just as in the existing ISO writer.
pub struct FolderVolume {
    len: u64,
    extents: Vec<Extent>,
    cached_file: Option<(usize, File)>,
}

impl FolderVolume {
    pub fn open(input: &Path) -> Result<Self> {
        let mut root = scan(input, 0)?;
        if root.children.is_none() {
            return bad("Disc layout input must be a folder");
        }
        let mut next = 33;
        assign(&mut root, &mut next)?;
        make_table(&mut root);
        let mut descriptor = vec![0u8; SECTOR as usize];
        descriptor[..20].copy_from_slice(MAGIC);
        descriptor[20..24].copy_from_slice(&root.sector.to_le_bytes());
        descriptor[24..28].copy_from_slice(&root.size.to_le_bytes());
        descriptor[2028..].copy_from_slice(MAGIC);
        let mut extents = vec![Extent {
            start: 0x10000,
            len: SECTOR,
            data: ExtentData::Bytes(descriptor),
        }];
        fn collect(n: Node, extents: &mut Vec<Extent>) {
            let data = if n.children.is_some() {
                ExtentData::Bytes(n.table)
            } else {
                ExtentData::File(n.path)
            };
            // Empty files and directories occupy no bytes and can share sectors.
            if n.size > 0 {
                extents.push(Extent {
                    start: n.sector as u64 * SECTOR,
                    len: n.size as u64,
                    data,
                });
            }
            if let Some(children) = n.children {
                for child in children {
                    collect(child, extents);
                }
            }
        }
        collect(root, &mut extents);
        Ok(Self {
            len: (next * SECTOR).div_ceil(65536) * 65536,
            extents,
            cached_file: None,
        })
    }

    pub fn len(&self) -> u64 {
        self.len
    }

    pub fn read_at(&mut self, offset: u64, buf: &mut [u8]) -> Result<()> {
        let end = offset
            .checked_add(buf.len() as u64)
            .filter(|end| *end <= self.len)
            .ok_or("Folder volume read out of bounds")?;
        if buf.is_empty() {
            return Ok(());
        }
        buf.fill(0);
        let mut index = self
            .extents
            .partition_point(|extent| extent.start + extent.len <= offset);
        while let Some(extent) = self.extents.get(index) {
            if extent.start >= end {
                break;
            }
            let start = extent.start.max(offset);
            let count = (end.min(extent.start + extent.len) - start) as usize;
            let within = start - extent.start;
            let target = (start - offset) as usize;
            let dest = &mut buf[target..target + count];
            match &extent.data {
                ExtentData::Bytes(data) => {
                    dest.copy_from_slice(&data[within as usize..within as usize + count]);
                }
                ExtentData::File(path) => {
                    if self.cached_file.as_ref().map(|(i, _)| *i) != Some(index) {
                        let file = File::open(path)?;
                        if file.metadata()?.len() != extent.len {
                            return bad(format!(
                                "Input file changed while building GOD: {}",
                                path.display()
                            ));
                        }
                        self.cached_file = Some((index, file));
                    }
                    let file = &mut self.cached_file.as_mut().unwrap().1;
                    file.seek(SeekFrom::Start(within))?;
                    file.read_exact(dest)?;
                    if file.metadata()?.len() != extent.len {
                        return bad(format!(
                            "Input file changed while building GOD: {}",
                            path.display()
                        ));
                    }
                }
            }
            index += 1;
        }
        Ok(())
    }
}
fn preorder(lo: usize, hi: usize, o: &mut Vec<usize>) {
    if lo >= hi {
        return;
    }
    let m = (lo + hi) / 2;
    o.push(m);
    preorder(lo, m, o);
    preorder(m + 1, hi, o);
}
fn positions(cs: &[Node]) -> (Vec<usize>, usize) {
    let mut order = Vec::new();
    preorder(0, cs.len(), &mut order);
    let mut at = vec![0; cs.len()];
    let mut pos = 0usize;
    for i in order {
        let len = (14 + cs[i].name.len()).div_ceil(4) * 4;
        if pos % 2048 + len > 2048 {
            pos = pos.div_ceil(2048) * 2048;
        }
        at[i] = pos;
        pos += len;
    }
    (at, pos)
}
fn scan(p: &Path, depth: usize) -> Result<Node> {
    if depth > 128 {
        return bad("Folder depth exceeds 128");
    }
    let meta = fs::symlink_metadata(p)?;
    if meta.file_type().is_symlink() || meta.file_attributes_reparse() {
        return bad("Links and reparse points are not accepted as input");
    }
    let name = p
        .file_name()
        .unwrap_or_default()
        .to_string_lossy()
        .to_string();
    if meta.is_file() {
        return Ok(Node {
            name,
            path: p.into(),
            size: u32::try_from(meta.len()).map_err(|_| "Xbox files must be smaller than 4 GiB")?,
            sector: 0,
            children: None,
            table: vec![],
        });
    }
    let mut children = Vec::new();
    let mut names = BTreeSet::new();
    for e in fs::read_dir(p)? {
        let e = e?;
        let n = e
            .file_name()
            .into_string()
            .map_err(|_| "Invalid file name")?;
        if !safe_name(&n) || !n.is_ascii() || n.len() > 255 || !names.insert(n.to_ascii_lowercase())
        {
            return bad("Unsupported or duplicate Xbox file name");
        }
        children.push(scan(&e.path(), depth + 1)?);
    }
    children.sort_by_key(|c| c.name.to_ascii_uppercase());
    let (_, len) = positions(&children);
    if len > 262144 {
        return bad("Directory exceeds 16-bit Xbox tree link capacity");
    }
    Ok(Node {
        name,
        path: p.into(),
        size: len as u32,
        sector: 0,
        children: Some(children),
        table: vec![255; len],
    })
}
trait Reparse {
    fn file_attributes_reparse(&self) -> bool;
}
impl Reparse for fs::Metadata {
    fn file_attributes_reparse(&self) -> bool {
        #[cfg(windows)]
        {
            use std::os::windows::fs::MetadataExt;
            self.file_attributes() & 0x400 != 0
        }
        #[cfg(not(windows))]
        {
            false
        }
    }
}
fn assign(n: &mut Node, next: &mut u64) -> Result<()> {
    n.sector = u32::try_from(*next).map_err(|_| "Image too large")?;
    *next += (n.size as u64).div_ceil(SECTOR);
    if let Some(cs) = n.children.as_mut() {
        for c in cs {
            assign(c, next)?;
        }
    }
    Ok(())
}
fn make_table(n: &mut Node) {
    let Some(cs) = n.children.as_mut() else {
        return;
    };
    for c in cs.iter_mut() {
        make_table(c);
    }
    // Root must occupy entry zero; emit a balanced tree in preorder.
    let (at, _) = positions(cs);
    fn link(lo: usize, hi: usize, at: &[usize]) -> u16 {
        if lo >= hi {
            0
        } else {
            (at[(lo + hi) / 2] / 4) as u16
        }
    }
    fn fill(lo: usize, hi: usize, cs: &[Node], at: &[usize], b: &mut [u8]) {
        if lo >= hi {
            return;
        }
        let m = (lo + hi) / 2;
        let p = at[m];
        let c = &cs[m];
        b[p..p + 2].copy_from_slice(&link(lo, m, at).to_le_bytes());
        b[p + 2..p + 4].copy_from_slice(&link(m + 1, hi, at).to_le_bytes());
        b[p + 4..p + 8].copy_from_slice(&c.sector.to_le_bytes());
        b[p + 8..p + 12].copy_from_slice(&c.size.to_le_bytes());
        b[p + 12] = if c.children.is_some() { 0x10 } else { 0x20 };
        b[p + 13] = c.name.len() as u8;
        b[p + 14..p + 14 + c.name.len()].copy_from_slice(c.name.as_bytes());
        fill(lo, m, cs, at, b);
        fill(m + 1, hi, cs, at, b);
    }
    fill(0, cs.len(), cs, &at, &mut n.table);
}
fn write_node(n: &Node, f: &mut File, done: &mut u64, total: u64) -> Result<()> {
    f.seek(SeekFrom::Start(n.sector as u64 * SECTOR))?;
    if let Some(cs) = &n.children {
        f.write_all(&n.table)?;
        for c in cs {
            write_node(c, f, done, total)?;
        }
    } else {
        let mut input = File::open(&n.path)?;
        let mut buf = vec![0; 1024 * 1024];
        let mut remaining = n.size as u64;
        while remaining > 0 {
            let want = remaining.min(buf.len() as u64) as usize;
            input.read_exact(&mut buf[..want])?;
            f.write_all(&buf[..want])?;
            remaining -= want as u64;
            *done += want as u64;
            progress("iso", *done, total);
        }
        if input.metadata()?.len() != n.size as u64 {
            return bad("Input file changed while building ISO");
        }
    }
    Ok(())
}
fn sum(n: &Node) -> u64 {
    match &n.children {
        Some(cs) => cs.iter().map(sum).sum(),
        None => n.size as u64,
    }
}
pub fn build(input: &Path, out: &Path) -> Result<()> {
    let mut root = scan(input, 0)?;
    let total = sum(&root);
    let mut next = 33;
    assign(&mut root, &mut next)?;
    make_table(&mut root);
    let mut f = OpenOptions::new().write(true).create_new(true).open(out)?;
    f.set_len((next * SECTOR).div_ceil(65536) * 65536)?;
    let mut d = [0u8; 2048];
    d[..20].copy_from_slice(MAGIC);
    d[20..24].copy_from_slice(&root.sector.to_le_bytes());
    d[24..28].copy_from_slice(&root.size.to_le_bytes());
    d[2028..].copy_from_slice(MAGIC);
    f.seek(SeekFrom::Start(0x10000))?;
    f.write_all(&d)?;
    write_node(&root, &mut f, &mut 0, total)?;
    f.sync_all()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn workspace(name: &str) -> PathBuf {
        let unique = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("target/test-data")
            .join(format!("{name}-{}-{unique}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn folder_reads_match_iso_across_files_padding_and_seeks() {
        let work = workspace("folder-layout");
        let source = work.join("source");
        fs::create_dir_all(source.join("nested/empty")).unwrap();
        fs::create_dir_all(source.join("another-empty")).unwrap();
        for (i, size) in [0, 1, 2047, 2048, 2049, 4097, 900_001]
            .into_iter()
            .enumerate()
        {
            let data: Vec<u8> = (0..size).map(|n| (n * 31 + i) as u8).collect();
            fs::write(source.join(format!("nested/file-{i}.bin")), data).unwrap();
        }
        for i in 0..180 {
            fs::write(
                source.join(format!("{i:03}-{}.bin", "x".repeat(i % 100))),
                [i as u8; 17],
            )
            .unwrap();
        }
        let iso = work.join("reference.iso");
        build(&source, &iso).unwrap();
        let expected = fs::read(iso).unwrap();
        let mut folder = FolderVolume::open(&source).unwrap();
        assert_eq!(folder.len(), expected.len() as u64);
        let mut at = 0;
        while at < expected.len() {
            let size = (13_117usize).min(expected.len() - at);
            let mut bytes = vec![0xaa; size];
            folder.read_at(at as u64, &mut bytes).unwrap();
            assert_eq!(bytes, expected[at..at + size]);
            at += size;
        }
        let mut random = 0x12345678u64;
        for _ in 0..1500 {
            random = random.wrapping_mul(6364136223846793005).wrapping_add(1);
            let at = (random as usize) % expected.len();
            let size = ((random >> 32) as usize % 8193).min(expected.len() - at);
            let mut bytes = vec![0xff; size];
            folder.read_at(at as u64, &mut bytes).unwrap();
            assert_eq!(bytes, expected[at..at + size]);
        }
        folder.read_at(folder.len(), &mut []).unwrap();
        assert!(folder.read_at(folder.len(), &mut [0]).is_err());
        assert!(folder.read_at(u64::MAX, &mut [0; 2]).is_err());
    }

    #[test]
    fn empty_folder_matches_iso() {
        let work = workspace("empty-folder");
        let source = work.join("source");
        fs::create_dir(&source).unwrap();
        let iso = work.join("reference.iso");
        build(&source, &iso).unwrap();
        let mut folder = FolderVolume::open(&source).unwrap();
        let mut bytes = vec![0xff; folder.len() as usize];
        folder.read_at(0, &mut bytes).unwrap();
        assert_eq!(bytes, fs::read(iso).unwrap());
    }

    #[test]
    fn changed_source_length_is_rejected_even_when_cached() {
        let work = workspace("changed-source");
        let source = work.join("source");
        fs::create_dir(&source).unwrap();
        let file = source.join("file.bin");
        fs::write(&file, [3; 100]).unwrap();
        let mut volume = Volume::Folder(FolderVolume::open(&source).unwrap());
        let file_sector = entries(&mut volume).unwrap()[0].sector as u64 * SECTOR;
        volume.read_at(file_sector, &mut [0]).unwrap();
        fs::write(&file, [7; 101]).unwrap();
        assert!(volume.read_at(file_sector, &mut [0]).is_err());
    }
}
