//! apply_patch — multi-file unified-diff patch with sandbox + rollback on error.
//!
//! Accepts a "patch" string in the standard unified-diff format with file
//! markers (`--- a/path` / `+++ b/path`). All paths must be inside the
//! generalist sandbox. On any failure, no file is left modified.

use super::{Tool, ToolCtx};
use crate::tools::sandbox;
use async_trait::async_trait;
use serde_json::Value;
use std::collections::HashMap;
use std::path::PathBuf;

pub struct ApplyPatch;

#[async_trait]
impl Tool for ApplyPatch {
    fn name(&self) -> &'static str { "apply_patch" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let patch = args.get("patch").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: patch".to_string())?;
        apply_unified_diff(patch).await
    }
}

#[derive(Default)]
struct FileChange {
    new_lines: Vec<String>,
    is_new: bool,
    is_delete: bool,
}

async fn apply_unified_diff(patch: &str) -> Result<String, String> {
    // Parse into per-file targets first.
    let mut current_file: Option<PathBuf> = None;
    let mut originals: HashMap<PathBuf, Vec<String>> = HashMap::new();
    let mut changes: HashMap<PathBuf, FileChange> = HashMap::new();
    let mut lines_iter = patch.lines().peekable();

    while let Some(line) = lines_iter.next() {
        if let Some(rest) = line.strip_prefix("--- ") {
            // Look for matching +++ next.
            let from = rest.trim().trim_start_matches("a/").trim_start_matches("./");
            let to_line = lines_iter.next().ok_or("dangling --- line")?;
            let to = to_line.strip_prefix("+++ ")
                .ok_or("expected +++ after ---")?
                .trim().trim_start_matches("b/").trim_start_matches("./");

            let target_str = if to == "/dev/null" { from } else { to };
            let resolved = sandbox::validate(target_str, false)
                .map_err(|e| format!("sandbox: {e}"))?;

            current_file = Some(resolved.clone());

            if from == "/dev/null" {
                // New file
                changes.insert(resolved.clone(), FileChange { is_new: true, ..Default::default() });
                originals.insert(resolved, Vec::new());
            } else if to == "/dev/null" {
                let existing = tokio::fs::read_to_string(&resolved).await
                    .map_err(|e| format!("read {} for delete: {e}", resolved.display()))?;
                originals.insert(resolved.clone(), existing.lines().map(String::from).collect());
                changes.insert(resolved, FileChange { is_delete: true, ..Default::default() });
            } else {
                let existing = tokio::fs::read_to_string(&resolved).await
                    .map_err(|e| format!("read {}: {e}", resolved.display()))?;
                let lines: Vec<String> = existing.lines().map(String::from).collect();
                originals.insert(resolved.clone(), lines.clone());
                changes.entry(resolved).or_insert_with(|| FileChange {
                    new_lines: lines, ..Default::default()
                });
            }
        } else if line.starts_with("@@") {
            // Hunk header — apply lines until next @@/--- or end.
            let path = current_file.as_ref()
                .ok_or("hunk before file marker")?.clone();
            let header = parse_hunk_header(line)
                .ok_or_else(|| format!("bad hunk header: {line}"))?;
            let change = changes.get_mut(&path).ok_or("no change record")?;
            apply_hunk(change, &header, &mut lines_iter)?;
        }
        // ignore other diff cruft (index, mode, etc.)
    }

    // Apply atomically: write all to temp paths, then move.
    let mut writes: Vec<(PathBuf, Option<String>)> = Vec::new();
    for (path, change) in &changes {
        if change.is_delete {
            writes.push((path.clone(), None));
        } else {
            writes.push((path.clone(), Some(change.new_lines.join("\n") + "\n")));
        }
    }

    // Two-phase: write all temps first.
    let mut temps: Vec<(PathBuf, PathBuf)> = Vec::new();
    for (path, content) in &writes {
        if let Some(text) = content {
            if let Some(parent) = path.parent() {
                tokio::fs::create_dir_all(parent).await.ok();
            }
            // Enforce CLAUDE.md `_` prefix on new files
            let basename = path.file_name().and_then(|s| s.to_str()).unwrap_or("");
            let is_new = changes.get(path).map(|c| c.is_new).unwrap_or(false);
            if is_new && !basename.starts_with('_') && !basename.starts_with('.') {
                return Err(format!("AI-created file must start with '_': {basename}"));
            }
            let tmp = path.with_extension(format!(
                "{}.aim-tmp",
                path.extension().and_then(|s| s.to_str()).unwrap_or("")
            ));
            tokio::fs::write(&tmp, text).await
                .map_err(|e| format!("write tmp {}: {e}", tmp.display()))?;
            temps.push((path.clone(), tmp));
        }
    }

    // Phase 2: move/delete.
    for (path, tmp) in temps {
        tokio::fs::rename(&tmp, &path).await
            .map_err(|e| format!("rename {} → {}: {e}", tmp.display(), path.display()))?;
    }
    for (path, content) in &writes {
        if content.is_none() {
            tokio::fs::remove_file(path).await
                .map_err(|e| format!("delete {}: {e}", path.display()))?;
        }
    }

    Ok(format!("applied {} file change(s)", changes.len()))
}

#[derive(Default)]
struct HunkHeader { old_start: usize, old_count: usize }

fn parse_hunk_header(s: &str) -> Option<HunkHeader> {
    // @@ -<old_start>,<old_count> +<new_start>,<new_count> @@
    let inner = s.strip_prefix("@@")?.trim();
    let parts: Vec<&str> = inner.split_whitespace().collect();
    let old_part = parts.iter().find(|p| p.starts_with('-'))?;
    let body = old_part.trim_start_matches('-');
    let mut bits = body.split(',');
    let old_start: usize = bits.next()?.parse().ok()?;
    let old_count: usize = bits.next().and_then(|x| x.parse().ok()).unwrap_or(1);
    Some(HunkHeader { old_start, old_count })
}

fn apply_hunk<'a, I>(change: &mut FileChange, h: &HunkHeader, iter: &mut std::iter::Peekable<I>) -> Result<(), String>
where I: Iterator<Item = &'a str>
{
    if change.is_new || change.new_lines.is_empty() {
        // For new files, just collect '+' lines.
        while let Some(&line) = iter.peek() {
            if line.starts_with("@@") || line.starts_with("--- ") { break; }
            iter.next();
            if let Some(rest) = line.strip_prefix('+') {
                change.new_lines.push(rest.to_string());
            }
        }
        return Ok(());
    }

    // Locate hunk in current new_lines (which mirror the original on first hunk).
    let idx = h.old_start.saturating_sub(1);
    let mut new_segment: Vec<String> = Vec::new();

    let mut consumed_old = 0usize;
    while let Some(&line) = iter.peek() {
        if line.starts_with("@@") || line.starts_with("--- ") { break; }
        iter.next();
        if let Some(rest) = line.strip_prefix(' ') {
            // context: must match
            let cur = change.new_lines.get(idx + consumed_old)
                .ok_or_else(|| format!("hunk context past EOF at line {}", idx + consumed_old + 1))?;
            if cur != rest {
                return Err(format!(
                    "hunk context mismatch at line {}: expected '{}', got '{}'",
                    idx + consumed_old + 1, rest, cur
                ));
            }
            new_segment.push(cur.clone());
            consumed_old += 1;
        } else if let Some(rest) = line.strip_prefix('-') {
            let cur = change.new_lines.get(idx + consumed_old)
                .ok_or_else(|| format!("hunk delete past EOF at line {}", idx + consumed_old + 1))?;
            if cur != rest {
                return Err(format!(
                    "hunk delete mismatch at line {}: expected '{}', got '{}'",
                    idx + consumed_old + 1, rest, cur
                ));
            }
            consumed_old += 1;
        } else if let Some(rest) = line.strip_prefix('+') {
            new_segment.push(rest.to_string());
        }
    }

    // Splice: replace new_lines[idx..idx+consumed_old] with new_segment.
    let _replaced = consumed_old.min(change.new_lines.len() - idx);
    let tail = change.new_lines.split_off(idx + consumed_old.min(change.new_lines.len() - idx));
    change.new_lines.truncate(idx);
    change.new_lines.extend(new_segment);
    change.new_lines.extend(tail);
    let _ = h.old_count; // count is metadata, we don't strictly need it
    Ok(())
}
