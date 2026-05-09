//! Long-running bash jobs. Whitelist + sandbox same as `bash`, but the call
//! returns immediately with a `job_id`; output is fetched via bash_output and
//! the job can be killed via bash_kill.

use super::{Tool, ToolCtx};
use async_trait::async_trait;
use parking_lot::Mutex;
use serde_json::{json, Value};
use std::sync::Arc;
use tokio::process::Child;

#[derive(Clone)]
pub struct JobRegistry {
    inner: Arc<Mutex<std::collections::HashMap<String, JobHandle>>>,
}

pub struct JobHandle {
    pub child: Child,
    pub stdout_buf: Arc<Mutex<String>>,
    pub stderr_buf: Arc<Mutex<String>>,
    pub status: Arc<Mutex<JobStatus>>,
}

#[derive(Clone, Debug)]
pub enum JobStatus {
    Running,
    Done(#[allow(dead_code)] i32),
    Killed,
}

impl JobRegistry {
    pub fn new() -> Self { Self { inner: Arc::new(Mutex::new(Default::default())) } }
}

impl Default for JobRegistry { fn default() -> Self { Self::new() } }

pub struct BashAsync { pub jobs: JobRegistry }
pub struct BashStatus { pub jobs: JobRegistry }
pub struct BashOutput { pub jobs: JobRegistry }
pub struct BashKill   { pub jobs: JobRegistry }

#[async_trait]
impl Tool for BashAsync {
    fn name(&self) -> &'static str { "bash_async" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let cmd = args.get("command").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: command".to_string())?;

        // Reuse the strict whitelist from bash_tool by re-validating shell metacharacters.
        for ch in &['|', ';', '&', '`', '$', '>', '<', '\n', '\\'] {
            if cmd.contains(*ch) {
                return Err(format!("forbidden shell metachar: {ch:?}"));
            }
        }
        let mut parts = cmd.split_whitespace();
        let head = parts.next().unwrap_or("");
        if !["cargo", "pytest", "mix", "elixir", "python", "python3"].contains(&head) {
            // bash_async is only for known long-running tools; refuse the rest.
            return Err(format!("bash_async: '{head}' not in async-allowed list"));
        }
        let rest: Vec<&str> = parts.collect();
        for arg in &rest {
            if matches!(*arg, "-c" | "-e" | "--exec" | "-delete") {
                return Err(format!("blocked flag: {arg}"));
            }
        }

        let mut child = tokio::process::Command::new(head)
            .args(&rest)
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn().map_err(|e| format!("spawn: {e}"))?;

        let id = uuid::Uuid::new_v4().to_string();
        let stdout_buf = Arc::new(Mutex::new(String::new()));
        let stderr_buf = Arc::new(Mutex::new(String::new()));
        let status = Arc::new(Mutex::new(JobStatus::Running));

        if let Some(out) = child.stdout.take() { spawn_reader(out, stdout_buf.clone()); }
        if let Some(err) = child.stderr.take() { spawn_reader(err, stderr_buf.clone()); }

        // Watcher to set Done.
        let st = status.clone();
        let id_cloned = id.clone();
        let jobs = self.jobs.inner.clone();
        tokio::spawn(async move {
            // We don't have child here anymore (moved into registry). Use a polling approach.
            loop {
                tokio::time::sleep(std::time::Duration::from_millis(200)).await;
                let mut guard = jobs.lock();
                let still_running = if let Some(h) = guard.get_mut(&id_cloned) {
                    match h.child.try_wait() {
                        Ok(Some(s)) => {
                            let code: i32 = s.code().unwrap_or(-1);
                            *st.lock() = JobStatus::Done(code);
                            false
                        }
                        Ok(None) => true,
                        Err(_) => false,
                    }
                } else { false };
                drop(guard);
                if !still_running { break; }
            }
        });

        let handle = JobHandle { child, stdout_buf, stderr_buf, status };
        self.jobs.inner.lock().insert(id.clone(), handle);
        Ok(json!({ "job_id": id }).to_string())
    }
}

fn spawn_reader<R>(mut r: R, buf: Arc<Mutex<String>>)
where R: tokio::io::AsyncRead + Unpin + Send + 'static
{
    use tokio::io::AsyncReadExt;
    tokio::spawn(async move {
        let mut tmp = [0u8; 4096];
        loop {
            match r.read(&mut tmp).await {
                Ok(0) | Err(_) => break,
                Ok(n) => {
                    let s = String::from_utf8_lossy(&tmp[..n]);
                    buf.lock().push_str(&s);
                }
            }
        }
    });
}

#[async_trait]
impl Tool for BashStatus {
    fn name(&self) -> &'static str { "bash_status" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let id = args.get("job_id").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: job_id".to_string())?;
        let guard = self.jobs.inner.lock();
        let h = guard.get(id).ok_or_else(|| format!("unknown job_id: {id}"))?;
        let st = h.status.lock().clone();
        Ok(format!("{:?}", st))
    }
}

#[async_trait]
impl Tool for BashOutput {
    fn name(&self) -> &'static str { "bash_output" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let id = args.get("job_id").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: job_id".to_string())?;
        let guard = self.jobs.inner.lock();
        let h = guard.get(id).ok_or_else(|| format!("unknown job_id: {id}"))?;
        let stdout = h.stdout_buf.lock().clone();
        let stderr = h.stderr_buf.lock().clone();
        let status = h.status.lock().clone();
        Ok(format!("[status {status:?}]\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"))
    }
}

#[async_trait]
impl Tool for BashKill {
    fn name(&self) -> &'static str { "bash_kill" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let id = args.get("job_id").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: job_id".to_string())?;
        let mut guard = self.jobs.inner.lock();
        let h = guard.get_mut(id).ok_or_else(|| format!("unknown job_id: {id}"))?;
        h.child.start_kill().map_err(|e| format!("kill: {e}"))?;
        *h.status.lock() = JobStatus::Killed;
        Ok("killed".into())
    }
}
