//! aim-fs-restore — extract a tar archive produced by `aim-fs-backup`.
//!
//! Refuses to overwrite a non-empty AIM root unless `--force` is given.
//! Verifies sha256 against the .manifest.json sibling if present.
//!
//! Usage:
//!     aim-fs-restore --tar <path>.tar [--into <aim_root>] [--force]
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

fn main() -> anyhow::Result<()> {
    let mut tar_path: Option<PathBuf> = None;
    let mut into: Option<PathBuf> = None;
    let mut force = false;

    let argv: Vec<String> = std::env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        match argv[i].as_str() {
            "-h" | "--help" => {
                print_help();
                return Ok(());
            }
            "--tar" => {
                tar_path = argv.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--into" => {
                into = argv.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--force" => {
                force = true;
                i += 1;
            }
            other => anyhow::bail!("unknown arg: {other}"),
        }
    }
    let tar_path = tar_path.ok_or_else(|| anyhow::anyhow!("--tar required"))?;
    let into = into
        .or_else(|| std::env::var("AIM_FS_ROOT").ok().map(PathBuf::from))
        .or_else(|| {
            std::env::var("HOME")
                .ok()
                .map(|h| PathBuf::from(h).join(".aim_fs"))
        })
        .ok_or_else(|| anyhow::anyhow!("--into required"))?;

    if into.exists()
        && fs::read_dir(&into)
            .map(|mut it| it.next().is_some())
            .unwrap_or(false)
        && !force
    {
        anyhow::bail!(
            "target {} is non-empty; pass --force to overwrite",
            into.display()
        );
    }

    // Verify sha256 if a manifest is present alongside the tar.
    let manifest_path = tar_path.with_extension("manifest.json");
    if manifest_path.exists() {
        let manifest: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(&manifest_path)?)?;
        if let Some(expected) = manifest.get("sha256").and_then(|v| v.as_str()) {
            let actual = sha256_file(&tar_path)?;
            if expected != actual {
                anyhow::bail!("sha256 mismatch — expected {expected}, got {actual}");
            }
            println!("✓ sha256 ok");
        }
    }

    fs::create_dir_all(&into)?;
    let n = extract_tar(&tar_path, &into)?;
    println!("restored {n} files into {}", into.display());
    Ok(())
}

fn sha256_file(p: &Path) -> anyhow::Result<String> {
    let mut h = Sha256::new();
    let mut f = File::open(p)?;
    let mut buf = [0u8; 8192];
    loop {
        let n = f.read(&mut buf)?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    Ok(format!("sha256:{}", hex::encode(h.finalize())))
}

fn extract_tar(tar: &Path, into: &Path) -> anyhow::Result<usize> {
    let mut f = File::open(tar)?;
    let mut count = 0;
    loop {
        let mut header = [0u8; 512];
        let read = read_full(&mut f, &mut header)?;
        if read == 0 {
            break;
        }
        if header.iter().all(|b| *b == 0) {
            break; // end-of-archive
        }
        let path = c_string(&header[..100]);
        if path.is_empty() {
            break;
        }
        let size = parse_octal(&header[124..136]);
        let typ = header[156];
        if typ != b'0' && typ != 0 {
            // Skip non-regular entries — backup only writes regular files.
            skip_aligned(&mut f, size)?;
            continue;
        }
        let dst = into.join(&path);
        if let Some(parent) = dst.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut out = File::create(&dst)?;
        copy_n(&mut f, &mut out, size)?;
        // Skip padding to 512 boundary.
        let pad = (512 - (size % 512)) % 512;
        let mut sink = vec![0u8; pad as usize];
        f.read_exact(&mut sink).ok();
        count += 1;
    }
    Ok(count)
}

fn read_full(r: &mut impl Read, buf: &mut [u8]) -> std::io::Result<usize> {
    let mut total = 0;
    while total < buf.len() {
        match r.read(&mut buf[total..]) {
            Ok(0) => break,
            Ok(n) => total += n,
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        }
    }
    Ok(total)
}

fn c_string(bytes: &[u8]) -> String {
    let end = bytes.iter().position(|b| *b == 0).unwrap_or(bytes.len());
    String::from_utf8_lossy(&bytes[..end]).to_string()
}

fn parse_octal(bytes: &[u8]) -> u64 {
    let s = c_string(bytes);
    u64::from_str_radix(s.trim(), 8).unwrap_or(0)
}

fn copy_n(r: &mut impl Read, w: &mut impl Write, mut n: u64) -> std::io::Result<()> {
    let mut buf = [0u8; 8192];
    while n > 0 {
        let to_read = (buf.len() as u64).min(n) as usize;
        let got = r.read(&mut buf[..to_read])?;
        if got == 0 {
            break;
        }
        w.write_all(&buf[..got])?;
        n -= got as u64;
    }
    Ok(())
}

fn skip_aligned(r: &mut impl Read, n: u64) -> std::io::Result<()> {
    let aligned = ((n + 511) / 512) * 512;
    let mut left = aligned;
    let mut buf = [0u8; 8192];
    while left > 0 {
        let to_read = (buf.len() as u64).min(left) as usize;
        let got = r.read(&mut buf[..to_read])?;
        if got == 0 {
            break;
        }
        left -= got as u64;
    }
    Ok(())
}

fn print_help() {
    println!(
        "aim-fs-restore — extract an aim-fs-backup archive\n\n\
         USAGE: aim-fs-restore --tar <path>.tar [--into <aim_root>] [--force]\n\n\
         Verifies sha256 against the .manifest.json sibling if present.\n\
         Refuses to overwrite a non-empty target unless --force."
    );
}
