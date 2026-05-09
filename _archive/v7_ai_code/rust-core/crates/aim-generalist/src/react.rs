//! ReAct loop. Two run modes:
//!  - `Runner::run(...)` — sync, returns aggregated `RunResult`.
//!  - `Runner::run_streaming(...)` — pushes `Event` per step into a `mpsc::Sender`.
//! The model returns either { "tool": <name>, "args": {...} } or { "final": "..." }.

use crate::llm_client::{LlmClient, Message};
use crate::tools::{Registry, ToolCall, ToolResult};
use crate::interrupt::InterruptRegistry;
use crate::speculative::PrefetchCache;
use serde::{Deserialize, Serialize};
use std::sync::atomic::Ordering;
use tokio::sync::mpsc;

const SYSTEM_PROMPT: &str = r#"You are AIM Generalist — a tool-using assistant.

On every turn respond with a SINGLE JSON object, no prose around it:
  - { "tool": "<name>", "args": { ... } }
  - { "final": "<answer text>" }

═════ Tools ═════════════════════════════════════════════════════════════════
read_file       { path: "Patients/X/MEMORY.md", max_bytes?: 32768 }
write_file      { path: "Patients/X/_summary.md", content: "..." }
                 (filename MUST start with '_' for AI-generated files)
glob            { pattern: "Patients/*/MEMORY.md", root?: "." }
grep            { pattern: "diagnosis", path: "Patients/X" }
bash            { command: "ls Patients/X", timeout_ms?: 30000 }
                 (whitelist; no python -c, no find -delete, no shell metacharacters)
bash_async      { command: "pytest tests/" } → {"job_id": "..."}
bash_status     { job_id: "..." }
bash_output     { job_id: "..." }
bash_kill       { job_id: "..." }
http_get        { url: "https://..." }
web_search      { query: "...", max_results?: 8 }
llm_ask         { prompt: "...", system?: "..." }   (delegate to aim-llm)
notes           { op: "set"|"get"|"list", key?: "...", value?: "..." }
memory_recall   { query: "patient X CBC", k?: 5 }   (semantic via aim-rag)
memory_save     { text: "...", id?: "...", metadata?: {...} }
verify_pmid     { pmid: "38510429" }
verify_doi      { doi: "10.3389/fphar.2024..." }
search_pubmed   { query: "centriole aging", retmax?: 8 }
apply_patch     { patch: "--- a/file\n+++ b/file\n@@..." }
                 (atomic multi-file unified-diff; new files MUST start with '_')
kernel_check    { action: "email_send"|"git_push_public"|...,
                  text?: "...", context?: { privacy_consent?: bool, user_confirmed?: bool } }
delegate_parallel { tasks: ["task1", "task2", ...] }
                 (≤8 tasks; runs in parallel + synthesises)

═════ Rules ═════════════════════════════════════════════════════════════════
1. NEVER fabricate file contents, PMIDs, DOIs, or quotes. Read or verify first.
2. Citations: any PMID/DOI in the final answer MUST come from verify_pmid or
   verify_doi output. Untrusted citations = block via kernel_check.
3. Egress to email/git/web/telegram requires kernel_check first.
4. Prefer specific tools (read_file > bash cat).
5. If a tool errors, explain in "final"; don't retry blindly.
6. AI-generated files MUST be named '_<purpose>.<ext>' and live under sandbox.
7. Reply ONLY with the JSON object — no markdown fences, no prose.

═════ Examples ══════════════════════════════════════════════════════════════
User: "What's in Patients/SMITH_JOHN_2000_01_01/MEMORY.md?"
You:  { "tool": "read_file", "args": { "path": "Patients/SMITH_JOHN_2000_01_01/MEMORY.md" } }

User: "Verify PMID 38510429."
You:  { "tool": "verify_pmid", "args": { "pmid": "38510429" } }

User: "Search PubMed for centriolar aging and rank top 5."
You:  { "tool": "search_pubmed", "args": { "query": "centriolar aging", "retmax": 5 } }

User: "Patch agents/foo.py to remove the deprecated call."
You:  { "tool": "read_file", "args": { "path": "agents/foo.py" } }
      (then later: { "tool": "apply_patch", "args": { "patch": "..." } })
"#;

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct TraceEntry {
    pub step: usize,
    pub tool: Option<String>,
    pub args: Option<serde_json::Value>,
    pub result_preview: Option<String>,
    pub error: Option<String>,
}

#[derive(Serialize, Clone, Debug)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Event {
    Start { task: String, max_iters: usize },
    LlmRequest { step: usize },
    LlmResponse { step: usize, raw: String },
    ToolCall { step: usize, tool: String, args: serde_json::Value },
    ToolResult { step: usize, tool: String, output: String },
    ToolError { step: usize, tool: String, error: String },
    Final { answer: String, tools_used: Vec<String> },
    Error { error: String },
}

pub struct RunResult {
    pub answer: String,
    pub trace: Vec<TraceEntry>,
    pub tools_used: Vec<String>,
}

pub struct Runner {
    llm: LlmClient,
    tools: Registry,
    pub interrupts: InterruptRegistry,
    pub prefetch: PrefetchCache,
}

impl Runner {
    pub fn from_env() -> Self {
        Self {
            llm: LlmClient::from_env(),
            tools: Registry::with_defaults(),
            interrupts: InterruptRegistry::new(),
            prefetch: PrefetchCache::new(),
        }
    }

    pub fn tool_names(&self) -> Vec<String> { self.tools.names() }

    pub async fn run(
        &self,
        task: &str,
        extra_system: Option<&str>,
        max_iters: usize,
    ) -> anyhow::Result<RunResult> {
        let (tx, mut rx) = mpsc::channel::<Event>(64);
        let task = task.to_string();
        let extra = extra_system.map(String::from);

        let res = self.run_inner(&task, extra.as_deref(), max_iters, Some(tx)).await;
        // Drain any remaining events (we ignore them in sync mode).
        while rx.try_recv().is_ok() {}
        res
    }

    pub async fn run_streaming(
        &self,
        task: &str,
        extra_system: Option<&str>,
        max_iters: usize,
        tx: mpsc::Sender<Event>,
    ) -> anyhow::Result<RunResult> {
        self.run_inner(task, extra_system, max_iters, Some(tx)).await
    }

    async fn run_inner(
        &self,
        task: &str,
        extra_system: Option<&str>,
        max_iters: usize,
        tx: Option<mpsc::Sender<Event>>,
    ) -> anyhow::Result<RunResult> {
        let system = match extra_system {
            Some(s) if !s.is_empty() => format!("{SYSTEM_PROMPT}\n\nAdditional context:\n{s}"),
            _ => SYSTEM_PROMPT.to_string(),
        };

        let mut messages = vec![
            Message { role: "system".into(), content: system },
            Message { role: "user".into(),   content: task.into() },
        ];
        let mut trace = Vec::new();
        let mut tools_used: Vec<String> = Vec::new();

        // JSONL session log (~/.cache/aim/sessions/<run_id>.jsonl)
        let run_id = uuid::Uuid::new_v4().to_string();
        let log_path = session_log_path(&run_id);
        let log_writer = open_session_log(&log_path).await;
        let interrupt_flag = self.interrupts.register(run_id.clone());

        emit(&tx, Event::Start { task: task.into(), max_iters }).await;
        write_log(&log_writer, &Event::Start { task: task.into(), max_iters }).await;

        // Auto-compact threshold (chars; ~4 chars/token, default 30K tokens = 120K chars).
        let compact_threshold: usize = std::env::var("AIM_COMPACT_CHARS")
            .ok().and_then(|s| s.parse().ok()).unwrap_or(120_000);

        for step in 1..=max_iters {
            // Cooperative cancel.
            if interrupt_flag.load(Ordering::SeqCst) {
                let ev = Event::Error { error: format!("interrupted at step {step}") };
                emit(&tx, ev.clone()).await;
                write_log(&log_writer, &ev).await;
                self.interrupts.release(&run_id);
                return Ok(RunResult {
                    answer: "(interrupted)".into(),
                    trace,
                    tools_used: dedup(tools_used),
                });
            }

            // Auto-compact if history is too large.
            let total_chars: usize = messages.iter().map(|m| m.content.len()).sum();
            if total_chars > compact_threshold && messages.len() > 4 {
                if let Ok(compacted) = compact_history(&self.llm, &messages).await {
                    messages = compacted;
                    tracing::info!("auto-compact: history shrunk from {total_chars} chars");
                }
            }

            let ev = Event::LlmRequest { step };
            emit(&tx, ev.clone()).await;
            write_log(&log_writer, &ev).await;
            let raw = self.llm.chat(&messages).await?;
            let ev = Event::LlmResponse { step, raw: raw.clone() };
            emit(&tx, ev.clone()).await;
            write_log(&log_writer, &ev).await;

            let json = match extract_json(&raw) {
                Some(v) => v,
                None => {
                    let ev = Event::Error { error: format!("step {step}: model returned non-JSON") };
                    emit(&tx, ev.clone()).await;
                    write_log(&log_writer, &ev).await;
                    anyhow::bail!("step {step}: model returned non-JSON: {raw}");
                }
            };

            if let Some(ans) = json.get("final").and_then(|v| v.as_str()) {
                let mut answer = ans.to_string();
                // Optional auto-trigger self-critique (env-gated for cost control).
                if std::env::var("AIM_AUTO_CRITIQUE").as_deref() == Ok("1") {
                    if let Ok(revised) = self_critique(&self.llm, task, &answer).await {
                        if !revised.trim().is_empty() && revised != answer {
                            tracing::info!("self-critique applied; answer revised");
                            answer = revised;
                        }
                    }
                }
                let ev = Event::Final {
                    answer: answer.clone(),
                    tools_used: dedup(tools_used.clone()),
                };
                emit(&tx, ev.clone()).await;
                write_log(&log_writer, &ev).await;
                self.interrupts.release(&run_id);
                return Ok(RunResult {
                    answer,
                    trace,
                    tools_used: dedup(tools_used),
                });
            }

            let name = match json.get("tool").and_then(|v| v.as_str()) {
                Some(n) => n.to_string(),
                None => {
                    let ev = Event::Error { error: format!("step {step}: no tool/final key") };
                    emit(&tx, ev.clone()).await;
                    write_log(&log_writer, &ev).await;
                    anyhow::bail!("step {step}: no `tool` or `final` key");
                }
            };
            let args = json.get("args").cloned().unwrap_or(serde_json::Value::Null);
            tools_used.push(name.clone());

            let ev = Event::ToolCall { step, tool: name.clone(), args: args.clone() };
            emit(&tx, ev.clone()).await;
            write_log(&log_writer, &ev).await;

            // Speculative prefetch: if model is reading a file, kick off
            // sibling preload in the background.
            if name == "read_file" {
                if let Some(p) = args.get("path").and_then(|v| v.as_str()) {
                    self.prefetch.schedule_siblings(p);
                }
            }

            let call = ToolCall { name: name.clone(), args: args.clone() };
            match self.tools.dispatch(&call).await {
                ToolResult::Ok(out) => {
                    let preview_text = preview(&out, 800);
                    trace.push(TraceEntry {
                        step, tool: Some(name.clone()),
                        args: Some(args),
                        result_preview: Some(preview_text.clone()),
                        error: None,
                    });
                    let ev = Event::ToolResult { step, tool: name.clone(), output: preview_text };
                    emit(&tx, ev.clone()).await;
                    write_log(&log_writer, &ev).await;
                    messages.push(Message { role: "assistant".into(), content: raw });
                    messages.push(Message {
                        role: "user".into(),
                        content: format!("[tool_result {name}] {out}")
                    });
                }
                ToolResult::Err(e) => {
                    trace.push(TraceEntry {
                        step, tool: Some(name.clone()),
                        args: Some(args),
                        result_preview: None,
                        error: Some(e.clone()),
                    });
                    let ev = Event::ToolError { step, tool: name.clone(), error: e.clone() };
                    emit(&tx, ev.clone()).await;
                    write_log(&log_writer, &ev).await;
                    messages.push(Message { role: "assistant".into(), content: raw });
                    messages.push(Message {
                        role: "user".into(),
                        content: format!("[tool_error {name}] {e}")
                    });
                }
            }
        }

        let answer = format!("(no final answer in {max_iters} steps)");
        let ev = Event::Final {
            answer: answer.clone(),
            tools_used: dedup(tools_used.clone()),
        };
        emit(&tx, ev.clone()).await;
        write_log(&log_writer, &ev).await;
        self.interrupts.release(&run_id);
        Ok(RunResult { answer, trace, tools_used: dedup(tools_used) })
    }

    pub fn interrupt(&self, run_id: &str) -> bool {
        self.interrupts.signal(run_id)
    }
}

// ── JSONL session log ─────────────────────────────────────────────────────────

use tokio::io::AsyncWriteExt;
use tokio::sync::Mutex as TokioMutex;
use std::sync::Arc;

type LogWriter = Option<Arc<TokioMutex<tokio::fs::File>>>;

fn session_log_path(run_id: &str) -> std::path::PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/home/oem".into());
    std::path::PathBuf::from(format!("{home}/.cache/aim/sessions/{run_id}.jsonl"))
}

async fn open_session_log(path: &std::path::Path) -> LogWriter {
    if std::env::var("AIM_NO_SESSION_LOG").as_deref() == Ok("1") { return None; }
    if let Some(parent) = path.parent() {
        if tokio::fs::create_dir_all(parent).await.is_err() { return None; }
    }
    match tokio::fs::OpenOptions::new()
        .create(true).append(true).open(path).await
    {
        Ok(f) => Some(Arc::new(TokioMutex::new(f))),
        Err(_) => None,
    }
}

async fn compact_history(llm: &LlmClient, messages: &[Message]) -> anyhow::Result<Vec<Message>> {
    if messages.len() <= 4 { return Ok(messages.to_vec()); }
    // Keep system + first user + last 2 messages; summarise the middle.
    let (head, tail) = messages.split_at(2);
    let last_two_idx = tail.len().saturating_sub(2);
    let middle = &tail[..last_two_idx];
    let last = &tail[last_two_idx..];

    let middle_text = middle.iter()
        .map(|m| format!("[{}] {}", m.role, m.content))
        .collect::<Vec<_>>()
        .join("\n---\n");

    let summary = llm.chat(&[
        Message { role: "system".into(),
            content: "Compress these tool-call traces into a 200-word factual summary. \
                      Preserve file paths, PMIDs, DOIs, error messages. Drop preamble.".into() },
        Message { role: "user".into(), content: middle_text },
    ]).await?;

    let mut out: Vec<Message> = head.to_vec();
    out.push(Message {
        role: "user".into(),
        content: format!("[history_compacted]\n{summary}")
    });
    out.extend(last.iter().cloned());
    Ok(out)
}

async fn self_critique(llm: &LlmClient, task: &str, answer: &str) -> anyhow::Result<String> {
    let raw = llm.chat(&[
        Message { role: "system".into(),
            content: "You are an adversarial reviewer. Reply ONLY with the corrected answer, \
                      no commentary. If the answer is solid, return it verbatim.".into() },
        Message { role: "user".into(),
            content: format!("Task:\n{task}\n\nAnswer:\n{answer}\n\nReturn the final, fact-checked answer:") },
    ]).await?;
    Ok(raw.trim().to_string())
}

async fn write_log(writer: &LogWriter, ev: &Event) {
    let Some(w) = writer else { return; };
    let mut line = match serde_json::to_string(ev) {
        Ok(s) => s,
        Err(_) => return,
    };
    line.push('\n');
    let mut f = w.lock().await;
    let _ = f.write_all(line.as_bytes()).await;
}

async fn emit(tx: &Option<mpsc::Sender<Event>>, ev: Event) {
    if let Some(tx) = tx { let _ = tx.send(ev).await; }
}

fn dedup(mut v: Vec<String>) -> Vec<String> {
    let mut seen = std::collections::HashSet::new();
    v.retain(|x| seen.insert(x.clone()));
    v
}

fn preview(s: &str, n: usize) -> String {
    if s.len() <= n { s.to_string() } else {
        let mut i = n;
        while !s.is_char_boundary(i) && i > 0 { i -= 1; }
        format!("{}…[+{} bytes]", &s[..i], s.len() - i)
    }
}

fn extract_json(s: &str) -> Option<serde_json::Value> {
    if let Ok(v) = serde_json::from_str(s) { return Some(v); }
    let bytes = s.as_bytes();
    let mut depth = 0i32;
    let mut start = None;
    let mut best: Option<(usize, usize)> = None;
    for (i, &b) in bytes.iter().enumerate() {
        match b {
            b'{' => { if depth == 0 { start = Some(i); } depth += 1; }
            b'}' => {
                depth -= 1;
                if depth == 0 {
                    if let Some(st) = start {
                        let cand = (st, i + 1);
                        if best.is_none_or(|(s2, e2)| (i + 1 - st) > (e2 - s2)) { best = Some(cand); }
                    }
                }
            }
            _ => {}
        }
    }
    let (st, en) = best?;
    serde_json::from_str(&s[st..en]).ok()
}
