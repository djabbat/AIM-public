//! web_search — DuckDuckGo HTML lite scraper.

use super::{Tool, ToolCtx};
use async_trait::async_trait;
use regex::Regex;
use serde_json::Value;

pub struct WebSearch;

#[async_trait]
impl Tool for WebSearch {
    fn name(&self) -> &'static str { "web_search" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let q = args.get("query").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: query".to_string())?;
        let n = args.get("max_results").and_then(|v| v.as_u64()).unwrap_or(8).min(20);

        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(15))
            .user_agent("Mozilla/5.0 (compatible; AIM-bot/0.1)")
            .build().map_err(|e| e.to_string())?;
        let url = format!("https://html.duckduckgo.com/html/?q={}",
            urlencoding::encode(q));
        let html = client.get(&url).send().await
            .map_err(|e| format!("ddg: {e}"))?
            .text().await.map_err(|e| format!("ddg body: {e}"))?;

        // Extract <a class="result__a" href="..."> ... </a>
        let re = Regex::new(r#"(?s)<a\s+[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>"#).unwrap();
        let snippet_re = Regex::new(r#"(?s)<a\s+[^>]*class="result__snippet"[^>]*>(.*?)</a>"#).unwrap();

        let mut links: Vec<String> = Vec::new();
        for cap in re.captures_iter(&html).take(n as usize) {
            let url = strip_html(&cap[1]);
            let title = strip_html(&cap[2]);
            links.push(format!("- {title}\n  {url}"));
        }
        for (i, cap) in snippet_re.captures_iter(&html).take(n as usize).enumerate() {
            let s = strip_html(&cap[1]);
            if i < links.len() { links[i].push_str(&format!("\n  {s}")); }
        }
        if links.is_empty() {
            return Ok(format!("(no results for: {q})"));
        }
        Ok(links.join("\n\n"))
    }
}

fn strip_html(s: &str) -> String {
    let no_tags = Regex::new(r"<[^>]+>").unwrap().replace_all(s, "");
    let trimmed = no_tags.trim();
    // Decode common entities.
    trimmed.replace("&amp;", "&")
        .replace("&lt;", "<").replace("&gt;", ">")
        .replace("&quot;", "\"").replace("&#39;", "'")
        .replace("&nbsp;", " ")
}
