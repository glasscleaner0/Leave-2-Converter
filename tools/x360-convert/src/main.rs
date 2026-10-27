mod disc;
mod god;
mod hash;
mod stfs;
mod volume;
use std::{
    path::Path,
    sync::{
        Mutex,
        atomic::{AtomicBool, Ordering},
    },
    time::Instant,
};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
fn bad<T>(s: impl Into<String>) -> Result<T> {
    Err(std::io::Error::new(std::io::ErrorKind::InvalidData, s.into()).into())
}
fn le32(b: &[u8], p: usize) -> u32 {
    u32::from_le_bytes(b[p..p + 4].try_into().unwrap())
}
fn be32(b: &[u8], p: usize) -> u32 {
    u32::from_be_bytes(b[p..p + 4].try_into().unwrap())
}
static QUIET: AtomicBool = AtomicBool::new(false);
static LAST: Mutex<Option<Instant>> = Mutex::new(None);
fn progress(stage: &str, done: u64, total: u64) {
    if QUIET.load(Ordering::Relaxed) {
        return;
    }
    let mut last = LAST.lock().unwrap();
    if done == total || last.is_none_or(|t| t.elapsed().as_millis() > 500) {
        eprintln!("progress\t{stage}\t{done}\t{total}");
        *last = Some(Instant::now());
    }
}
fn usage() {
    println!(
        "x360-convert 0.2.0\n\n  inspect INPUT\n  list INPUT\n  manifest INPUT\n  extract INPUT OUTPUT_FOLDER\n  iso INPUT OUTPUT.iso\n  god INPUT OUTPUT_FOLDER [--title NAME] [--title-id HEX]\n  verify-god PACKAGE\n  list-dlc STFS_PACKAGE\n  extract-dlc STFS_PACKAGE OUTPUT_FOLDER\n\nINPUT: GOD package file, Xbox ISO, or extracted folder (iso/god).\nFolder-to-GOD streams directly; no temporary ISO is created.\nOutputs must not exist; output parent folders must exist. Originals are read only.\n--quiet suppresses progress. Progress uses stderr; results use stdout.\nGenerated GOD packages are unsigned and require a compatible modified console."
    );
}
fn inside(input: &Path, out: &Path) -> Result<()> {
    let source = input.canonicalize()?;
    let absolute = std::path::absolute(out)?;
    let parent = absolute
        .parent()
        .ok_or("Output has no parent")?
        .canonicalize()?;
    if parent.starts_with(&source) {
        return bad("Output must be outside the input folder");
    }
    Ok(())
}
fn run() -> Result<()> {
    let mut a: Vec<String> = std::env::args().skip(1).collect();
    if a.iter().any(|s| s == "--quiet") {
        QUIET.store(true, Ordering::Relaxed);
        a.retain(|s| s != "--quiet");
    }
    if a.is_empty() || ["--help", "-h", "help"].contains(&a[0].as_str()) {
        usage();
        return Ok(());
    }
    if a[0] == "--version" {
        println!("x360-convert 0.2.0");
        return Ok(());
    }
    if a.len() < 2 {
        return bad("Missing input path; use --help");
    }
    let input = Path::new(&a[1]);
    match a[0].as_str() {
        "list-dlc" | "extract-dlc" => {
            if a.len() != if a[0] == "list-dlc" { 2 } else { 3 } {
                return bad("Use list-dlc PACKAGE or extract-dlc PACKAGE OUTPUT_FOLDER");
            }
            let mut pkg = stfs::Package::open(input)?;
            if a[0] == "list-dlc" {
                pkg.list()?;
            } else {
                let out = Path::new(&a[2]);
                inside(input, out)?;
                pkg.extract(out)?;
                println!("complete\t{}", out.display());
            }
        }
        "inspect" | "list" | "manifest" | "verify-god" => {
            if a.len() != 2 {
                return bad("Unexpected arguments");
            }
            if a[0] == "verify-god" {
                return god::verify(input);
            }
            let mut v = volume::Volume::open(input)?;
            if a[0] == "manifest" {
                return disc::manifest(&mut v);
            }
            let es = disc::entries(&mut v)?;
            if a[0] == "list" {
                for e in es {
                    println!(
                        "{}\t{}\t{}",
                        if e.dir { "dir" } else { "file" },
                        e.size,
                        e.path
                    );
                }
            } else {
                println!(
                    "format\t{}",
                    match &v {
                        volume::Volume::God(_) => "GOD/SVOD",
                        _ => "XDVDFS ISO",
                    }
                );
                println!("bytes\t{}", v.len());
                println!("files\t{}", es.iter().filter(|e| !e.dir).count());
                println!("folders\t{}", es.iter().filter(|e| e.dir).count());
                println!(
                    "file_bytes\t{}",
                    es.iter()
                        .filter(|e| !e.dir)
                        .map(|e| e.size as u64)
                        .sum::<u64>()
                );
            }
        }
        "extract" | "iso" | "god" => {
            if a.len() < 3 {
                return bad("Missing output path");
            }
            let out = Path::new(&a[2]);
            if out.exists() {
                return bad("Output already exists; choose a new path");
            }
            inside(input, out)?;
            let mut title = "Xbox 360 Game".to_string();
            let mut id = None;
            let mut i = 3;
            while i < a.len() {
                if a[0] != "god" || i + 1 >= a.len() {
                    return bad("Unexpected option");
                }
                match a[i].as_str() {
                    "--title" => title = a[i + 1].clone(),
                    "--title-id" => {
                        id = Some(u32::from_str_radix(a[i + 1].trim_start_matches("0x"), 16)?)
                    }
                    _ => return bad("Unknown option"),
                };
                i += 2;
            }
            match a[0].as_str() {
                "extract" => disc::extract(&mut volume::Volume::open(input)?, out)?,
                "iso" => {
                    if input.is_dir() {
                        disc::build(input, out)?;
                    } else {
                        god::to_iso(&mut volume::Volume::open(input)?, out)?;
                    }
                }
                "god" => {
                    god::build(input, out, &title, id)?;
                }
                _ => unreachable!(),
            }
            println!("complete\t{}", out.display());
        }
        _ => return bad("Unknown command; use --help"),
    }
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("error\t{e}");
        std::process::exit(1);
    }
}
