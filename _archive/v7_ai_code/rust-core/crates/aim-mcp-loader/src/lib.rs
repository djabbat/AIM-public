//! aim-mcp-loader — MCP-style runtime tool registry.
//!
//! Port of `agents/mcp_loader.py`. Lets users add tools by dropping a
//! TOML config under `~/.aim/mcp/<name>.toml` (no AIM source edits).
//! Each server is a long-lived subprocess speaking JSON-RPC 2.0 over
//! stdio. The transport is abstracted behind [`RpcTransport`] so tests
//! exercise the registry/dispatch logic without spawning processes.
//!
//! TOML shape (verbatim with Python):
//!
//! ```toml
//! name = "weather"
//! command = ["python3", "-u", "-m", "my_weather_server"]
//! cwd = "~/projects/weather"        # optional
//! env = { OPENWEATHER_KEY = "..." }  # optional
//! autostart = true                   # default true
//! timeout_ms = 10000                 # default 10s
//! ```

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum McpError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("toml parse error: {0}")]
    Toml(String),
    #[error("invalid spec: {0}")]
    InvalidSpec(String),
    #[error("rpc error: {0}")]
    Rpc(String),
    #[error("not found: {0}")]
    NotFound(String),
}

pub type Result<T> = std::result::Result<T, McpError>;

// ── server spec ─────────────────────────────────────────────────────────────

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ServerSpec {
    pub name: String,
    pub command: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cwd: Option<String>,
    #[serde(default)]
    pub env: BTreeMap<String, String>,
    #[serde(default = "default_autostart")]
    pub autostart: bool,
    #[serde(default = "default_timeout_ms")]
    pub timeout_ms: u64,
}

fn default_autostart() -> bool {
    true
}
fn default_timeout_ms() -> u64 {
    10_000
}

/// Raw deserializer that allows `command` to be either a string (split via
/// shlex) or an array of strings — matches Python parse_spec.
#[derive(Debug, Deserialize)]
struct RawSpec {
    name: Option<String>,
    command: serde_json::Value,
    cwd: Option<String>,
    #[serde(default)]
    env: BTreeMap<String, String>,
    autostart: Option<bool>,
    timeout_ms: Option<u64>,
}

pub fn parse_spec(default_name: &str, raw_toml: &str) -> Result<ServerSpec> {
    let raw: RawSpec = toml::from_str(raw_toml).map_err(|e| McpError::Toml(e.to_string()))?;
    let command: Vec<String> = match &raw.command {
        serde_json::Value::String(s) => shlex::split(s)
            .ok_or_else(|| McpError::InvalidSpec("command shlex parse failed".into()))?,
        serde_json::Value::Array(arr) => arr
            .iter()
            .filter_map(|v| v.as_str().map(String::from))
            .collect(),
        _ => {
            return Err(McpError::InvalidSpec(
                "command must be a string or array of strings".into(),
            ))
        }
    };
    if command.is_empty() {
        return Err(McpError::InvalidSpec(format!(
            "{}: command must be non-empty",
            default_name
        )));
    }
    Ok(ServerSpec {
        name: raw.name.unwrap_or_else(|| default_name.to_string()),
        command,
        cwd: raw.cwd,
        env: raw.env,
        autostart: raw.autostart.unwrap_or(true),
        timeout_ms: raw.timeout_ms.unwrap_or(10_000),
    })
}

/// Discover all `*.toml` configs under `dir`. Bad entries are logged and skipped.
pub fn discover(dir: &Path) -> Result<Vec<ServerSpec>> {
    if !dir.exists() {
        return Ok(Vec::new());
    }
    let mut paths: Vec<PathBuf> = std::fs::read_dir(dir)?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| p.is_file() && p.extension().and_then(|s| s.to_str()) == Some("toml"))
        .collect();
    paths.sort();
    let mut out = Vec::new();
    for path in paths {
        let stem = path
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("?")
            .to_string();
        match std::fs::read_to_string(&path) {
            Ok(text) => match parse_spec(&stem, &text) {
                Ok(spec) => out.push(spec),
                Err(e) => tracing::warn!(?path, "skip MCP config: {}", e),
            },
            Err(e) => tracing::warn!(?path, "skip MCP config: {}", e),
        }
    }
    Ok(out)
}

// ── tool descriptor ─────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct ToolSpec {
    pub name: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub description: String,
    /// JSON-Schema-like blob; opaque here.
    #[serde(default)]
    pub schema: serde_json::Value,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ToolWithServer {
    pub server: String,
    pub name: String,
    pub description: String,
    pub schema: serde_json::Value,
}

// ── transport trait ─────────────────────────────────────────────────────────

/// JSON-RPC transport. Production binds to a stdio-Popen wrapper; tests
/// use the in-memory [`StubTransport`].
pub trait RpcTransport: Send + Sync {
    /// Send `method`/`params` and wait for the matching response.
    fn rpc(&self, method: &str, params: Option<serde_json::Value>) -> Result<serde_json::Value>;
    /// Stop the underlying process (best-effort).
    fn stop(&self);
}

// ── server runtime ──────────────────────────────────────────────────────────

pub struct McpServer {
    pub spec: ServerSpec,
    pub transport: Box<dyn RpcTransport>,
    tools: Mutex<Vec<ToolSpec>>,
}

impl McpServer {
    pub fn new(spec: ServerSpec, transport: Box<dyn RpcTransport>) -> Self {
        Self {
            spec,
            transport,
            tools: Mutex::new(Vec::new()),
        }
    }

    /// Refresh `tools` by calling `list_tools` over RPC. Best-effort: on
    /// failure we keep the existing list (or empty) and log.
    pub fn refresh_tools(&self) -> Result<usize> {
        match self.transport.rpc("list_tools", None) {
            Ok(serde_json::Value::Array(arr)) => {
                let mut new_tools = Vec::new();
                for v in arr {
                    if let Ok(t) = serde_json::from_value::<ToolSpec>(v) {
                        new_tools.push(t);
                    }
                }
                let count = new_tools.len();
                *self.tools.lock() = new_tools;
                Ok(count)
            }
            Ok(_) => {
                *self.tools.lock() = Vec::new();
                Ok(0)
            }
            Err(e) => {
                tracing::warn!("list_tools failed for {}: {}", self.spec.name, e);
                Err(e)
            }
        }
    }

    pub fn tools(&self) -> Vec<ToolSpec> {
        self.tools.lock().clone()
    }

    pub fn has_tool(&self, name: &str) -> bool {
        self.tools.lock().iter().any(|t| t.name == name)
    }

    /// Call a tool — returns the textual `result` (stringified for
    /// non-string return shapes).
    pub fn call(&self, tool: &str, args: serde_json::Value) -> Result<String> {
        let params = serde_json::json!({"name": tool, "args": args});
        let result = self.transport.rpc("call", Some(params))?;
        match result {
            serde_json::Value::String(s) => Ok(s),
            other => serde_json::to_string(&other).map_err(|e| McpError::Rpc(e.to_string())),
        }
    }

    pub fn stop(&self) {
        self.transport.stop();
    }
}

// ── registry ────────────────────────────────────────────────────────────────

#[derive(Default)]
pub struct Registry {
    servers: Mutex<BTreeMap<String, Arc<McpServer>>>,
}

impl Registry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn register(&self, server: Arc<McpServer>) {
        self.servers
            .lock()
            .insert(server.spec.name.clone(), server);
    }

    pub fn unregister(&self, name: &str) -> bool {
        let s = self.servers.lock().remove(name);
        match s {
            Some(srv) => {
                srv.stop();
                true
            }
            None => false,
        }
    }

    pub fn server_names(&self) -> Vec<String> {
        self.servers.lock().keys().cloned().collect()
    }

    pub fn get(&self, name: &str) -> Option<Arc<McpServer>> {
        self.servers.lock().get(name).cloned()
    }

    /// Union of tool descriptors with originating server name.
    pub fn list_tools(&self) -> Vec<ToolWithServer> {
        let map = self.servers.lock();
        let mut out = Vec::new();
        for srv in map.values() {
            for t in srv.tools() {
                out.push(ToolWithServer {
                    server: srv.spec.name.clone(),
                    name: t.name,
                    description: t.description,
                    schema: t.schema,
                });
            }
        }
        out
    }

    /// First server exposing `tool_name`.
    pub fn find_server(&self, tool_name: &str) -> Option<Arc<McpServer>> {
        let map = self.servers.lock();
        map.values().find(|s| s.has_tool(tool_name)).cloned()
    }

    /// Route a `call` to the right server. Mirrors Python's wrapped string
    /// errors (`ERROR:NOT_FOUND:…`, `ERROR:INTERNAL:…`).
    pub fn call(&self, tool_name: &str, args: serde_json::Value) -> String {
        let Some(srv) = self.find_server(tool_name) else {
            return format!("ERROR:NOT_FOUND:no MCP server exposes tool {:?}", tool_name);
        };
        match srv.call(tool_name, args) {
            Ok(s) => s,
            Err(e) => format!("ERROR:INTERNAL:{}", e),
        }
    }

    pub fn shutdown(&self) {
        let mut map = self.servers.lock();
        for (_, srv) in map.iter() {
            srv.stop();
        }
        map.clear();
    }

    pub fn len(&self) -> usize {
        self.servers.lock().len()
    }
    pub fn is_empty(&self) -> bool {
        self.servers.lock().is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    // ── stub transport ──────────────────────────────────────────────────────

    struct StubTransport {
        list_tools_response: serde_json::Value,
        call_responses: Mutex<Vec<serde_json::Value>>,
        calls_log: Mutex<Vec<(String, serde_json::Value)>>,
        stopped: Mutex<bool>,
    }
    impl StubTransport {
        fn new(tools: serde_json::Value, call_responses: Vec<serde_json::Value>) -> Self {
            Self {
                list_tools_response: tools,
                call_responses: Mutex::new(call_responses),
                calls_log: Mutex::new(Vec::new()),
                stopped: Mutex::new(false),
            }
        }
    }
    impl RpcTransport for StubTransport {
        fn rpc(&self, method: &str, params: Option<serde_json::Value>) -> Result<serde_json::Value> {
            self.calls_log
                .lock()
                .push((method.into(), params.clone().unwrap_or(serde_json::Value::Null)));
            match method {
                "list_tools" => Ok(self.list_tools_response.clone()),
                "call" => {
                    let mut r = self.call_responses.lock();
                    if r.is_empty() {
                        Err(McpError::Rpc("no canned response".into()))
                    } else {
                        Ok(r.remove(0))
                    }
                }
                _ => Err(McpError::Rpc(format!("unknown method {}", method))),
            }
        }
        fn stop(&self) {
            *self.stopped.lock() = true;
        }
    }

    fn spec(name: &str) -> ServerSpec {
        ServerSpec {
            name: name.into(),
            command: vec!["echo".into()],
            cwd: None,
            env: BTreeMap::new(),
            autostart: true,
            timeout_ms: 10_000,
        }
    }

    // ── parse_spec ──────────────────────────────────────────────────────────

    #[test]
    fn parse_spec_accepts_array_command() {
        let toml = r#"
            name = "weather"
            command = ["python3", "-m", "x"]
        "#;
        let s = parse_spec("weather", toml).unwrap();
        assert_eq!(s.name, "weather");
        assert_eq!(s.command, vec!["python3", "-m", "x"]);
        assert!(s.autostart);
        assert_eq!(s.timeout_ms, 10_000);
    }

    #[test]
    fn parse_spec_accepts_string_command_via_shlex() {
        let toml = r#"
            command = "python3 -m x"
        "#;
        let s = parse_spec("default", toml).unwrap();
        assert_eq!(s.command, vec!["python3", "-m", "x"]);
        assert_eq!(s.name, "default");
    }

    #[test]
    fn parse_spec_reads_optional_fields() {
        let toml = r#"
            command = ["x"]
            cwd = "/tmp"
            autostart = false
            timeout_ms = 5000
            env = { KEY = "v" }
        "#;
        let s = parse_spec("x", toml).unwrap();
        assert_eq!(s.cwd.as_deref(), Some("/tmp"));
        assert!(!s.autostart);
        assert_eq!(s.timeout_ms, 5000);
        assert_eq!(s.env.get("KEY").unwrap(), "v");
    }

    #[test]
    fn parse_spec_rejects_empty_command() {
        let toml = r#"
            command = []
        "#;
        assert!(parse_spec("x", toml).is_err());
    }

    #[test]
    fn parse_spec_rejects_invalid_toml() {
        assert!(parse_spec("x", "not valid toml [[").is_err());
    }

    // ── discover ────────────────────────────────────────────────────────────

    #[test]
    fn discover_returns_empty_for_missing_dir() {
        let tmp = TempDir::new().unwrap();
        let missing = tmp.path().join("nope");
        let v = discover(&missing).unwrap();
        assert!(v.is_empty());
    }

    #[test]
    fn discover_picks_up_toml_files_skips_invalid() {
        let tmp = TempDir::new().unwrap();
        std::fs::write(
            tmp.path().join("a.toml"),
            r#"command = ["foo"]"#,
        )
        .unwrap();
        std::fs::write(
            tmp.path().join("b.toml"),
            r#"command = ["bar"]"#,
        )
        .unwrap();
        std::fs::write(tmp.path().join("c.txt"), "ignored").unwrap();
        std::fs::write(tmp.path().join("d.toml"), "garbage [[[").unwrap();
        let v = discover(tmp.path()).unwrap();
        // a, b parsed; d skipped (warned)
        assert_eq!(v.len(), 2);
        let names: Vec<&str> = v.iter().map(|s| s.name.as_str()).collect();
        assert!(names.contains(&"a"));
        assert!(names.contains(&"b"));
    }

    #[test]
    fn discover_uses_filename_stem_when_name_omitted() {
        let tmp = TempDir::new().unwrap();
        std::fs::write(
            tmp.path().join("weather.toml"),
            r#"command = ["x"]"#,
        )
        .unwrap();
        let v = discover(tmp.path()).unwrap();
        assert_eq!(v[0].name, "weather");
    }

    // ── McpServer ───────────────────────────────────────────────────────────

    #[test]
    fn server_refresh_tools_populates_list() {
        let t = StubTransport::new(
            serde_json::json!([
                {"name": "forecast", "description": "weather", "schema": {}},
                {"name": "alerts"}
            ]),
            vec![],
        );
        let s = McpServer::new(spec("weather"), Box::new(t));
        let n = s.refresh_tools().unwrap();
        assert_eq!(n, 2);
        assert!(s.has_tool("forecast"));
        assert!(s.has_tool("alerts"));
    }

    #[test]
    fn server_call_returns_string_directly() {
        let t = StubTransport::new(serde_json::json!([]), vec![serde_json::json!("Tbilisi: 22°C")]);
        let s = McpServer::new(spec("weather"), Box::new(t));
        let out = s.call("forecast", serde_json::json!({"city": "Tbilisi"})).unwrap();
        assert_eq!(out, "Tbilisi: 22°C");
    }

    #[test]
    fn server_call_stringifies_non_string_result() {
        let t = StubTransport::new(
            serde_json::json!([]),
            vec![serde_json::json!({"temp": 22})],
        );
        let s = McpServer::new(spec("weather"), Box::new(t));
        let out = s.call("forecast", serde_json::json!({})).unwrap();
        assert!(out.contains("\"temp\":22"));
    }

    #[test]
    fn server_stop_calls_transport() {
        let stopped = Arc::new(Mutex::new(false));
        struct ProbeTransport(Arc<Mutex<bool>>);
        impl RpcTransport for ProbeTransport {
            fn rpc(&self, _: &str, _: Option<serde_json::Value>) -> Result<serde_json::Value> {
                Ok(serde_json::Value::Null)
            }
            fn stop(&self) {
                *self.0.lock() = true;
            }
        }
        let s = McpServer::new(spec("weather"), Box::new(ProbeTransport(stopped.clone())));
        s.stop();
        assert!(*stopped.lock());
    }

    // ── Registry routing ────────────────────────────────────────────────────

    fn make_server(name: &str, tool_names: &[&str], call_response: serde_json::Value) -> Arc<McpServer> {
        let tools_json: Vec<serde_json::Value> = tool_names
            .iter()
            .map(|n| serde_json::json!({"name": n}))
            .collect();
        let t = StubTransport::new(serde_json::Value::Array(tools_json), vec![call_response]);
        let srv = McpServer::new(spec(name), Box::new(t));
        srv.refresh_tools().unwrap();
        Arc::new(srv)
    }

    #[test]
    fn registry_register_and_get() {
        let r = Registry::new();
        r.register(make_server("s1", &["t1"], serde_json::json!("ok")));
        assert!(r.get("s1").is_some());
        assert_eq!(r.server_names(), vec!["s1".to_string()]);
    }

    #[test]
    fn registry_list_tools_unions_with_server_names() {
        let r = Registry::new();
        r.register(make_server("s1", &["a", "b"], serde_json::json!("x")));
        r.register(make_server("s2", &["c"], serde_json::json!("x")));
        let tools = r.list_tools();
        assert_eq!(tools.len(), 3);
        let with_server: Vec<(&str, &str)> = tools
            .iter()
            .map(|t| (t.server.as_str(), t.name.as_str()))
            .collect();
        assert!(with_server.contains(&("s1", "a")));
        assert!(with_server.contains(&("s1", "b")));
        assert!(with_server.contains(&("s2", "c")));
    }

    #[test]
    fn registry_find_server_routes_by_tool_name() {
        let r = Registry::new();
        r.register(make_server("s1", &["a"], serde_json::json!("x")));
        r.register(make_server("s2", &["b"], serde_json::json!("x")));
        let found = r.find_server("b").unwrap();
        assert_eq!(found.spec.name, "s2");
    }

    #[test]
    fn registry_call_routes_and_returns_result() {
        let r = Registry::new();
        r.register(make_server("s1", &["forecast"], serde_json::json!("hot")));
        let out = r.call("forecast", serde_json::json!({}));
        assert_eq!(out, "hot");
    }

    #[test]
    fn registry_call_unknown_tool_returns_not_found_string() {
        let r = Registry::new();
        let out = r.call("missing", serde_json::json!({}));
        assert!(out.starts_with("ERROR:NOT_FOUND:"));
        assert!(out.contains("missing"));
    }

    #[test]
    fn registry_unregister_returns_true_when_present() {
        let r = Registry::new();
        r.register(make_server("s1", &["a"], serde_json::json!("x")));
        assert!(r.unregister("s1"));
        assert!(!r.unregister("s1"));
    }

    #[test]
    fn registry_shutdown_clears_all() {
        let r = Registry::new();
        r.register(make_server("s1", &["a"], serde_json::json!("x")));
        r.register(make_server("s2", &["b"], serde_json::json!("x")));
        r.shutdown();
        assert!(r.is_empty());
    }
}
