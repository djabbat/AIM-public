use super::{Tool, ToolCtx};
use async_trait::async_trait;
use serde_json::Value;

pub struct Notes;

#[async_trait]
impl Tool for Notes {
    fn name(&self) -> &'static str { "notes" }
    async fn run(&self, args: &Value, ctx: &ToolCtx) -> Result<String, String> {
        let op = args.get("op").and_then(|v| v.as_str()).unwrap_or("get");
        let mut store = ctx.notes.lock().map_err(|e| e.to_string())?;
        match op {
            "set" => {
                let k = args.get("key").and_then(|v| v.as_str())
                    .ok_or_else(|| "missing key".to_string())?.to_string();
                let v = args.get("value").and_then(|v| v.as_str())
                    .ok_or_else(|| "missing value".to_string())?.to_string();
                store.insert(k.clone(), v);
                Ok(format!("set {k}"))
            }
            "get" => {
                let k = args.get("key").and_then(|v| v.as_str())
                    .ok_or_else(|| "missing key".to_string())?;
                Ok(store.get(k).cloned().unwrap_or_else(|| "(unset)".into()))
            }
            "list" => Ok(store.keys().cloned().collect::<Vec<_>>().join("\n")),
            _ => Err(format!("unknown op: {op}")),
        }
    }
}
