//! aim-fs-backup — create a hot backup of an AIM_FS data root.
//!
//! Strategy:
//!   1. Acquire SQLite read lock via `BEGIN IMMEDIATE` then `.backup` API
//!      to a snapshot file under `_service/backup/staging/aim_fs.db.snapshot`
//!      (safe even with the Phoenix Port writing concurrently — WAL).
//!   2. Stream-create a `tar` archive of `<aim_root>/` excluding the live
//!      WAL/SHM/journal files and `_service/tmp/`, including the snapshot.
//!   3. Compute sha256 of the resulting `.tar` and emit a manifest JSON
//!      next to it: `{file, size, sha256, entity_count, timestamp}`.
//!   4. Drop the staging snapshot.
//!
//! Output goes to `<aim_root>/_service/backup/<timestamp>.tar` + manifest.
//! No external compression dep — keep tar plain so `tar -tf` works.
//!
//! Usage:
//!     aim-fs-backup [--aim-root <path>] [--out <path>]
use rusqlite::{params, Connection};
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};

fn main() -> anyhow::Result<()> {
    let mut aim_root: Option<PathBuf> = None;
    let mut out_path: Option<PathBuf> = None;
    let argv: Vec<String> = std::env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        match argv[i].as_str() {
            "-h" | "--help" => {
                print_help();
                return Ok(());
            }
            "--aim-root" => {
                aim_root = argv.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--out" => {
                out_path = argv.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            other => anyhow::bail!("unknown arg: {other}"),
        }
    }
    let aim_root = aim_root
        .or_else(|| std::env::var("AIM_FS_ROOT").ok().map(PathBuf::from))
        .or_else(|| {
            std::env::var("HOME")
                .ok()
                .map(|h| PathBuf::from(h).join(".aim_fs"))
        })
        .ok_or_else(|| anyhow::anyhow!("--aim-root or AIM_FS_ROOT or $HOME required"))?;
    if !aim_root.exists() {
        anyhow::bail!("aim_root does not exist: {}", aim_root.display());
    }

    let now = chrono::Utc::now();
    let stamp = now.format("%Y%m%dT%H%M%SZ").to_string();
    let backup_dir = aim_root.join("_service").join("backup");
    fs::create_dir_all(&backup_dir)?;
    let staging = backup_dir.join("staging");
    fs::create_dir_all(&staging)?;
    let tar_path = out_path.unwrap_or_else(|| backup_dir.join(format!("{}.tar", stamp)));
    let manifest_path = tar_path.with_extension("manifest.json");

    // 1. Hot-backup SQLite via .backup API.
    let live_db = aim_root.join("_service").join("db").join("aim_fs.db");
    let snap_db = staging.join("aim_fs.db.snapshot");
    let entity_count = backup_sqlite(&live_db, &snap_db)?;

    // 2. Build tar archive.
    let f = File::create(&tar_path)?;
    let mut w = BufWriter::new(f);
    let mut hasher = Sha256::new();
    let mut bytes_written = 0u64;
    let added = write_tar(&aim_root, &snap_db, &staging, &mut w, &mut hasher, &mut bytes_written)?;
    w.flush()?;

    // 3. Manifest.
    let sha = format!("sha256:{}", hex::encode(hasher.finalize()));
    let manifest = serde_json::json!({
        "file": tar_path.display().to_string(),
        "size": bytes_written,
        "sha256": sha,
        "entity_count": entity_count,
        "files_in_archive": added,
        "timestamp": now.to_rfc3339(),
        "aim_root": aim_root.display().to_string(),
    });
    fs::write(&manifest_path, serde_json::to_string_pretty(&manifest)?)?;

    // 4. Drop staging snapshot.
    let _ = fs::remove_file(&snap_db);

    println!(
        "backup OK\n  tar:      {}\n  manifest: {}\n  bytes:    {}\n  sha256:   {}\n  entities: {}",
        tar_path.display(),
        manifest_path.display(),
        bytes_written,
        sha,
        entity_count
    );
    Ok(())
}

fn backup_sqlite(live: &Path, snapshot: &Path) -> anyhow::Result<i64> {
    if !live.exists() {
        // No DB yet — write empty marker so restore is symmetrical.
        fs::write(snapshot, b"")?;
        return Ok(0);
    }
    let src = Connection::open(live)?;
    let mut dst = Connection::open(snapshot)?;
    let backup = rusqlite::backup::Backup::new(&src, &mut dst)?;
    backup.run_to_completion(100, std::time::Duration::from_millis(0), None)?;
    drop(backup);
    let n: i64 = dst.query_row("SELECT COUNT(*) FROM entities", params![], |r| r.get(0))?;
    Ok(n)
}

// `_service/backup/` целиком исключается: внутри лежат предыдущие
// backup'ы (`<timestamp>.tar` + `.manifest.json`) — они derived data,
// бэкапить их в новый tar бессмысленно. Главное: walkdir() при
// итерации может встретить именно тот .tar, в который сейчас идёт
// запись — и начнёт читать тот же файл, что пишется. Архив растёт
// бесконечно (наблюдалось на 2026-05-08: 604 GB tar, содержащий сам
// себя). EXCLUDE_PREFIXES останавливает рекурсию на уровне walkdir.
const EXCLUDE_PREFIXES: &[&str] = &["_service/tmp/", "_service/backup/"];
const EXCLUDE_SUFFIXES: &[&str] = &["-wal", "-shm", ".journal"];

fn write_tar(
    aim_root: &Path,
    snapshot: &Path,
    staging: &Path,
    w: &mut impl Write,
    hasher: &mut Sha256,
    bytes_written: &mut u64,
) -> anyhow::Result<usize> {
    let mut count = 0;
    for entry in walkdir::WalkDir::new(aim_root) {
        let entry = entry?;
        if !entry.file_type().is_file() {
            continue;
        }
        let abs = entry.path();
        // Always include our snapshot (under staging/), but skip the live
        // DB + WAL siblings.
        if abs == snapshot {
            // pretend it's at _service/db/aim_fs.db inside the archive
            let rel = "_service/db/aim_fs.db";
            count += write_tar_entry(rel, abs, w, hasher, bytes_written)?;
            continue;
        }
        if abs.starts_with(staging) {
            continue;
        }
        let rel = abs.strip_prefix(aim_root)?.to_string_lossy().to_string();
        if EXCLUDE_PREFIXES.iter().any(|p| rel.starts_with(p)) {
            continue;
        }
        if EXCLUDE_SUFFIXES.iter().any(|s| rel.ends_with(s)) {
            continue;
        }
        // Skip the live aim_fs.db — we ship the snapshot instead.
        if rel == "_service/db/aim_fs.db" {
            continue;
        }
        count += write_tar_entry(&rel, abs, w, hasher, bytes_written)?;
    }
    // tar end-of-archive marker: two zero-filled 512-byte blocks.
    let zero = [0u8; 1024];
    write_all_h(w, hasher, &zero, bytes_written)?;
    Ok(count)
}

fn write_tar_entry(
    rel_path: &str,
    abs: &Path,
    w: &mut impl Write,
    hasher: &mut Sha256,
    bytes_written: &mut u64,
) -> anyhow::Result<usize> {
    let meta = abs.metadata()?;
    let size = meta.len();
    let header = ustar_header(rel_path, size, &meta)?;
    write_all_h(w, hasher, &header, bytes_written)?;
    let f = File::open(abs)?;
    let mut r = BufReader::new(f);
    let mut buf = [0u8; 8192];
    loop {
        let n = r.read(&mut buf)?;
        if n == 0 {
            break;
        }
        write_all_h(w, hasher, &buf[..n], bytes_written)?;
    }
    // Pad to 512-byte boundary.
    let pad = (512 - (size % 512)) % 512;
    if pad > 0 {
        let zeros = vec![0u8; pad as usize];
        write_all_h(w, hasher, &zeros, bytes_written)?;
    }
    Ok(1)
}

fn write_all_h(
    w: &mut impl Write,
    hasher: &mut Sha256,
    bytes: &[u8],
    bytes_written: &mut u64,
) -> anyhow::Result<()> {
    w.write_all(bytes)?;
    hasher.update(bytes);
    *bytes_written += bytes.len() as u64;
    Ok(())
}

fn ustar_header(rel_path: &str, size: u64, meta: &fs::Metadata) -> anyhow::Result<[u8; 512]> {
    use std::os::unix::fs::MetadataExt;
    let mut h = [0u8; 512];
    let path_bytes = rel_path.as_bytes();
    // ustar поддерживает имена до 255 байт через split на:
    //   • h[0..100]   — name (последний компонент)
    //   • h[345..500] — prefix (всё что перед последним /)
    // Финальный путь = "{prefix}/{name}". Split идёт по последнему /
    // так, чтобы name ≤ 100 и prefix ≤ 155.
    if path_bytes.len() <= 100 {
        h[..path_bytes.len()].copy_from_slice(path_bytes);
    } else {
        // Найти split-точку: последний '/' такой, что часть после него
        // ≤ 100 байт, а часть до — ≤ 155.
        let mut split: Option<usize> = None;
        for (i, &b) in path_bytes.iter().enumerate() {
            if b == b'/' {
                let prefix_len = i;
                let name_len = path_bytes.len() - i - 1;
                if name_len <= 100 && prefix_len <= 155 {
                    split = Some(i);
                    // продолжаем — берём САМЫЙ последний подходящий /,
                    // чтобы prefix был как можно длиннее (а name короче)
                }
            }
        }
        let i = split.ok_or_else(|| anyhow::anyhow!(
            "path too long for ustar (>255 bytes or unsplittable): {rel_path}"
        ))?;
        let prefix = &path_bytes[..i];
        let name = &path_bytes[i + 1..];
        h[..name.len()].copy_from_slice(name);
        h[345..345 + prefix.len()].copy_from_slice(prefix);
    }
    write_octal(&mut h[100..108], (meta.mode() & 0o7777) as u64, 8);
    write_octal(&mut h[108..116], meta.uid() as u64, 8);
    write_octal(&mut h[116..124], meta.gid() as u64, 8);
    write_octal(&mut h[124..136], size, 12);
    write_octal(&mut h[136..148], meta.mtime() as u64, 12);
    // Type flag: '0' = regular file.
    h[156] = b'0';
    // Magic + version: `ustar\000`.
    h[257..263].copy_from_slice(b"ustar ");
    h[263..265].copy_from_slice(b" \0");
    // Checksum field is initialized with spaces, then summed.
    h[148..156].copy_from_slice(b"        ");
    let mut csum: u64 = 0;
    for &b in h.iter() {
        csum += b as u64;
    }
    write_octal(&mut h[148..154], csum, 6);
    h[154] = 0;
    h[155] = b' ';
    Ok(h)
}

fn write_octal(field: &mut [u8], n: u64, width: usize) {
    let s = format!("{:0>width$o}", n, width = width.saturating_sub(1));
    let bytes = s.as_bytes();
    let copy_len = bytes.len().min(field.len() - 1);
    field[..copy_len].copy_from_slice(&bytes[..copy_len]);
    field[copy_len] = 0;
}

fn print_help() {
    println!(
        "aim-fs-backup — hot backup an AIM_FS data root\n\n\
         USAGE: aim-fs-backup [--aim-root <path>] [--out <path>]\n\n\
         If --out is omitted, archive lands at\n\
         <aim_root>/_service/backup/<timestamp>.tar plus a sibling .manifest.json"
    );
}
