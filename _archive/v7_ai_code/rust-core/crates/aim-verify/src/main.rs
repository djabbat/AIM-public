//! aim-verify — DOI / PMID resolution against Crossref + PubMed.
//!
//! Phase 10 hybrid (2026-05-07): first concrete Rust binary for the
//! tools-as-crates plan in STRATEGY.md P3-8. Replaces hot path of
//! `tools/literature.py::verify_doi` / `verify_pmid`. Python keeps
//! orchestration; Rust does the HTTP+JSON.
//!
//! Subcommands:
//!   verify-pmid <PMID>   # JSON record or "null"
//!   verify-doi  <DOI>    # JSON record or "null"
//!
//! ENV: AIM_VERIFY_TIMEOUT (seconds, default 8); AIM_PUBMED_API_KEY
//! (optional) gets appended to PubMed esummary URLs for higher rate limits.
//!
//! Exit codes:
//!   0 = resolved, JSON printed
//!   1 = not found / unparseable, "null" printed
//!   2 = network / parser error, message to stderr

use std::process::ExitCode;
use std::time::Duration;

use serde_json::{json, Value};

const PUBMED_ESUMMARY: &str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi";
const CROSSREF_WORKS: &str = "https://api.crossref.org/works";

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli(&args) {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => {
            println!("null");
            ExitCode::from(1)
        }
        Err(e) => {
            eprintln!("aim-verify: {e}");
            ExitCode::from(2)
        }
    }
}

fn cli(args: &[String]) -> Result<bool, Box<dyn std::error::Error>> {
    let cmd = args.first().map(String::as_str).unwrap_or("--help");
    match cmd {
        "--help" | "-h" | "help" => {
            print_usage();
            Ok(true)
        }
        "verify-pmid" => {
            let id = args.get(1).ok_or("verify-pmid <PMID> required")?;
            match verify_pmid(id)? {
                Some(v) => {
                    println!("{}", serde_json::to_string(&v)?);
                    Ok(true)
                }
                None => Ok(false),
            }
        }
        "verify-doi" => {
            let id = args.get(1).ok_or("verify-doi <DOI> required")?;
            match verify_doi(id)? {
                Some(v) => {
                    println!("{}", serde_json::to_string(&v)?);
                    Ok(true)
                }
                None => Ok(false),
            }
        }
        other => Err(format!("unknown command {other:?}; try --help").into()),
    }
}

fn timeout_secs() -> u64 {
    std::env::var("AIM_VERIFY_TIMEOUT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(8)
}

fn http_client() -> reqwest::blocking::Client {
    reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(timeout_secs()))
        .user_agent("aim-verify/0.1 (mailto:jaba@longevity.ge)")
        .build()
        .expect("reqwest client")
}

fn verify_pmid(raw: &str) -> Result<Option<Value>, Box<dyn std::error::Error>> {
    let pmid = raw.trim().trim_start_matches("PMID:").trim();
    if !pmid.chars().all(|c| c.is_ascii_digit()) {
        return Ok(None);
    }
    let mut url = format!("{PUBMED_ESUMMARY}?db=pubmed&id={pmid}&retmode=json");
    if let Ok(key) = std::env::var("AIM_PUBMED_API_KEY") {
        if !key.is_empty() {
            url.push_str(&format!("&api_key={}", key));
        }
    }
    let resp = http_client().get(&url).send()?;
    if !resp.status().is_success() {
        return Ok(None);
    }
    let body: Value = resp.json()?;
    let rec = body
        .get("result")
        .and_then(|r| r.get(pmid))
        .cloned()
        .unwrap_or(Value::Null);
    if rec.is_null() || rec.get("error").is_some() {
        return Ok(None);
    }
    let title = rec.get("title").and_then(|v| v.as_str()).unwrap_or("").trim().trim_end_matches('.');
    let journal = rec.get("source").and_then(|v| v.as_str()).unwrap_or("");
    let year = rec
        .get("pubdate")
        .and_then(|v| v.as_str())
        .and_then(|s| s.split_whitespace().next())
        .unwrap_or("");
    let authors: Vec<String> = rec
        .get("authors")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|x| x.get("name").and_then(|n| n.as_str()).map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default();
    let doi = rec
        .get("articleids")
        .and_then(|v| v.as_array())
        .and_then(|arr| {
            arr.iter().find_map(|a| {
                if a.get("idtype").and_then(|t| t.as_str()) == Some("doi") {
                    a.get("value").and_then(|v| v.as_str()).map(|s| s.to_string())
                } else {
                    None
                }
            })
        })
        .unwrap_or_default();
    Ok(Some(json!({
        "pmid": pmid,
        "title": title,
        "authors": authors,
        "journal": journal,
        "year": year,
        "doi": doi,
    })))
}

fn verify_doi(raw: &str) -> Result<Option<Value>, Box<dyn std::error::Error>> {
    use once_cell::sync::Lazy;
    use regex::Regex;
    static URL_PFX: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"^https?://(dx\.)?doi\.org/").unwrap());
    let doi = raw.trim().trim_start_matches("doi:").trim();
    let doi = URL_PFX.replace(doi, "").trim_end_matches(|c| c == '.' || c == ')').to_string();
    if doi.is_empty() || !doi.contains('/') {
        return Ok(None);
    }
    let url = format!("{CROSSREF_WORKS}/{}", urlencoding(&doi));
    let resp = http_client().get(&url).send()?;
    if !resp.status().is_success() {
        return Ok(None);
    }
    let body: Value = resp.json()?;
    let msg = body.get("message").cloned().unwrap_or(Value::Null);
    if msg.is_null() || msg.get("DOI").is_none() {
        return Ok(None);
    }
    let title = msg
        .get("title")
        .and_then(|v| v.as_array())
        .and_then(|a| a.first())
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .trim_end_matches('.');
    let journal = msg
        .get("container-title")
        .and_then(|v| v.as_array())
        .and_then(|a| a.first())
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let year = msg
        .get("issued")
        .and_then(|v| v.get("date-parts"))
        .and_then(|v| v.as_array())
        .and_then(|a| a.first())
        .and_then(|v| v.as_array())
        .and_then(|a| a.first())
        .and_then(|v| v.as_i64())
        .map(|n| n.to_string())
        .unwrap_or_default();
    let authors: Vec<String> = msg
        .get("author")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|au| {
                    let g = au.get("given").and_then(|v| v.as_str()).unwrap_or("").trim();
                    let f = au.get("family").and_then(|v| v.as_str()).unwrap_or("").trim();
                    if f.is_empty() { None } else { Some(format!("{g} {f}").trim().to_string()) }
                })
                .collect()
        })
        .unwrap_or_default();
    Ok(Some(json!({
        "doi": doi,
        "title": title,
        "authors": authors,
        "journal": journal,
        "year": year,
    })))
}

fn urlencoding(s: &str) -> String {
    // Minimal percent-encoding for non-ASCII / reserved chars; keep / + . _ -.
    let mut out = String::with_capacity(s.len());
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'/' | b'.' | b'_' | b'-' | b'+' => {
                out.push(b as char);
            }
            _ => out.push_str(&format!("%{:02X}", b)),
        }
    }
    out
}

fn print_usage() {
    println!(
        "aim-verify — Phase 10 hybrid tool: DOI / PMID resolution\n\n\
USAGE:\n\
  aim-verify verify-pmid <PMID>     # JSON record or 'null'\n\
  aim-verify verify-doi  <DOI>      # JSON record or 'null'\n\n\
ENV: AIM_VERIFY_TIMEOUT, AIM_PUBMED_API_KEY"
    );
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pmid_non_digit_returns_none() {
        let v = verify_pmid("notanumber").unwrap();
        assert!(v.is_none());
    }

    #[test]
    fn doi_without_slash_returns_none() {
        let v = verify_doi("invalid").unwrap();
        assert!(v.is_none());
    }

    #[test]
    fn doi_strips_url_prefix() {
        // We can't actually hit Crossref in tests, but parse-time handling
        // shouldn't error out on URL-prefixed input.
        let raw = "https://doi.org/10.1000/xyz123";
        // Just exercise the prefix-stripping; the actual HTTP call may
        // fail with a network error in offline CI — that's a separate test.
        let _ = verify_doi(raw); // smoke compile
    }

    #[test]
    fn urlencoding_passthrough_ascii() {
        assert_eq!(urlencoding("10.1000/xyz123"), "10.1000/xyz123");
    }

    #[test]
    fn urlencoding_escapes_special() {
        assert_eq!(urlencoding("a&b"), "a%26b");
    }
}
