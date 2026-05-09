use super::{Tool, ToolCtx};
use async_trait::async_trait;
use serde_json::Value;

pub struct Glob;

#[async_trait]
impl Tool for Glob {
    fn name(&self) -> &'static str { "glob" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let pattern = args.get("pattern").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: pattern".to_string())?;
        let root = args.get("root").and_then(|v| v.as_str()).unwrap_or(".");
        let full = if pattern.starts_with('/') { pattern.to_string() } else { format!("{root}/{pattern}") };

        let it = glob::glob(&full).map_err(|e| format!("glob: {e}"))?;
        let mut out = Vec::new();
        for entry in it.take(500) {
            match entry {
                Ok(p) => out.push(p.display().to_string()),
                Err(e) => out.push(format!("(err) {e}")),
            }
        }
        Ok(out.join("\n"))
    }
}

pub struct Grep;

#[async_trait]
impl Tool for Grep {
    fn name(&self) -> &'static str { "grep" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let pat = args.get("pattern").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: pattern".to_string())?;
        let path = args.get("path").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: path".to_string())?;
        let re = regex::Regex::new(pat).map_err(|e| format!("regex: {e}"))?;

        let mut hits = Vec::new();
        let walker = walk(path).await.map_err(|e| format!("walk {path}: {e}"))?;
        for file in walker.iter().take(2000) {
            if let Ok(bytes) = tokio::fs::read(file).await {
                let text = String::from_utf8_lossy(&bytes);
                for (i, line) in text.lines().enumerate() {
                    if re.is_match(line) {
                        hits.push(format!("{}:{}: {}", file, i + 1, line));
                        if hits.len() >= 200 { break; }
                    }
                }
                if hits.len() >= 200 { break; }
            }
        }
        Ok(hits.join("\n"))
    }
}

async fn walk(path: &str) -> std::io::Result<Vec<String>> {
    let meta = tokio::fs::metadata(path).await?;
    if meta.is_file() {
        return Ok(vec![path.to_string()]);
    }
    let mut out = Vec::new();
    let mut stack = vec![path.to_string()];
    while let Some(p) = stack.pop() {
        let mut rd = match tokio::fs::read_dir(&p).await { Ok(r) => r, Err(_) => continue };
        while let Ok(Some(e)) = rd.next_entry().await {
            let pp = e.path().display().to_string();
            if pp.contains("/.git/") || pp.contains("/target/") || pp.contains("/_build/") || pp.contains("/node_modules/") { continue; }
            let m = match e.metadata().await { Ok(m) => m, Err(_) => continue };
            if m.is_dir() { stack.push(pp); }
            else if m.is_file() { out.push(pp); }
            if out.len() > 5000 { return Ok(out); }
        }
    }
    Ok(out)
}
