use super::{Tool, ToolCtx};
use crate::tools::sandbox;
use async_trait::async_trait;
use serde_json::Value;

pub struct ReadFile;

#[async_trait]
impl Tool for ReadFile {
    fn name(&self) -> &'static str { "read_file" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let path = args.get("path").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: path".to_string())?;
        let max_bytes = args.get("max_bytes").and_then(|v| v.as_u64()).unwrap_or(64 * 1024) as usize;

        let resolved = sandbox::validate(path, true)?;
        let bytes = tokio::fs::read(&resolved).await
            .map_err(|e| format!("read {}: {e}", resolved.display()))?;
        let s = String::from_utf8_lossy(&bytes).into_owned();

        if s.len() > max_bytes {
            let head = sandbox::truncate_at_char(&s, max_bytes);
            Ok(format!("{head}…[truncated; total {} bytes]", s.len()))
        } else {
            Ok(s)
        }
    }
}

pub struct WriteFile;

#[async_trait]
impl Tool for WriteFile {
    fn name(&self) -> &'static str { "write_file" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let path = args.get("path").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: path".to_string())?;
        let content = args.get("content").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: content".to_string())?;

        let resolved = sandbox::validate(path, false)?;

        if let Some(parent) = resolved.parent() {
            tokio::fs::create_dir_all(parent).await.ok();
        }

        let basename = resolved.file_name()
            .and_then(|s| s.to_str()).unwrap_or("");
        if !basename.starts_with('_') && !basename.starts_with('.') {
            return Err(format!(
                "AI-generated files MUST start with '_' (CLAUDE.md): got '{basename}'"
            ));
        }

        tokio::fs::write(&resolved, content).await
            .map_err(|e| format!("write {}: {e}", resolved.display()))?;
        Ok(format!("wrote {} bytes to {}", content.len(), resolved.display()))
    }
}
