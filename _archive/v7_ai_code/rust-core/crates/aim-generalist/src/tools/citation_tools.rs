//! verify_pmid / verify_doi / search_pubmed — PubMed esummary + Crossref.
//!
//! Goal: per CLAUDE.md / feedback_deepseek_no_citations, every citation MUST
//! be PubMed- or Crossref-verified. These tools fail loudly on missing IDs.

use super::{Tool, ToolCtx};
use async_trait::async_trait;
use serde::Deserialize;
use serde_json::{json, Value};

fn http() -> reqwest::Client {
    reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(20))
        .user_agent("aim-generalist/0.1 (mailto:djabbat@gmail.com)")
        .build()
        .expect("reqwest")
}

pub struct VerifyPmid;

#[async_trait]
impl Tool for VerifyPmid {
    fn name(&self) -> &'static str { "verify_pmid" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let id = args.get("pmid").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: pmid".to_string())?
            .trim()
            .trim_start_matches("PMID:")
            .trim();
        if !id.chars().all(|c| c.is_ascii_digit()) {
            return Err(format!("not a numeric PMID: {id}"));
        }
        let url = format!(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={id}&retmode=json"
        );
        let v: Value = http().get(&url).send().await
            .map_err(|e| format!("pubmed: {e}"))?
            .error_for_status().map_err(|e| format!("pubmed: {e}"))?
            .json().await.map_err(|e| format!("pubmed parse: {e}"))?;

        let entry = v.get("result").and_then(|r| r.get(id)).cloned();
        match entry {
            None => Err(format!("PMID {id} not found in PubMed")),
            Some(e) => {
                let title = e.get("title").and_then(|x| x.as_str()).unwrap_or("?");
                let authors = e.get("authors")
                    .and_then(|x| x.as_array())
                    .map(|a| a.iter().filter_map(|au| au.get("name").and_then(|n| n.as_str()))
                        .collect::<Vec<_>>().join(", "))
                    .unwrap_or_default();
                let pubdate = e.get("pubdate").and_then(|x| x.as_str()).unwrap_or("");
                let journal = e.get("fulljournalname").and_then(|x| x.as_str()).unwrap_or("");
                Ok(format!("PMID:{id} VERIFIED\nTitle: {title}\nAuthors: {authors}\nJournal: {journal}\nDate: {pubdate}"))
            }
        }
    }
}

pub struct VerifyDoi;

#[async_trait]
impl Tool for VerifyDoi {
    fn name(&self) -> &'static str { "verify_doi" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let doi = args.get("doi").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: doi".to_string())?
            .trim()
            .trim_start_matches("https://doi.org/")
            .trim_start_matches("http://doi.org/")
            .trim_start_matches("doi:")
            .trim();
        if !doi.contains('/') {
            return Err(format!("not a DOI: {doi}"));
        }
        let url = format!("https://api.crossref.org/works/{}", urlencoding::encode(doi));
        let resp = http().get(&url).send().await.map_err(|e| format!("crossref: {e}"))?;
        if !resp.status().is_success() {
            return Err(format!("DOI {doi} not in Crossref ({})", resp.status()));
        }
        let v: Value = resp.json().await.map_err(|e| format!("crossref parse: {e}"))?;
        let m = v.get("message").cloned().unwrap_or(json!({}));
        let title = m.get("title").and_then(|x| x.as_array())
            .and_then(|a| a.first()).and_then(|x| x.as_str()).unwrap_or("?");
        let year = m.get("issued")
            .and_then(|x| x.get("date-parts")).and_then(|x| x.as_array())
            .and_then(|a| a.first()).and_then(|x| x.as_array())
            .and_then(|a| a.first()).and_then(|x| x.as_i64())
            .map(|y| y.to_string()).unwrap_or_default();
        let container = m.get("container-title").and_then(|x| x.as_array())
            .and_then(|a| a.first()).and_then(|x| x.as_str()).unwrap_or("");
        Ok(format!("DOI:{doi} VERIFIED\nTitle: {title}\nVenue: {container}\nYear: {year}"))
    }
}

pub struct SearchPubmed;

#[derive(Deserialize)]
struct ESearch { esearchresult: ESR }
#[derive(Deserialize)]
struct ESR { idlist: Vec<String> }

#[async_trait]
impl Tool for SearchPubmed {
    fn name(&self) -> &'static str { "search_pubmed" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let q = args.get("query").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: query".to_string())?;
        let n = args.get("retmax").and_then(|v| v.as_u64()).unwrap_or(8).min(50);

        let url = format!(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmode=json&retmax={n}&term={}",
            urlencoding::encode(q)
        );
        let r: ESearch = http().get(&url).send().await
            .map_err(|e| format!("pubmed: {e}"))?
            .error_for_status().map_err(|e| format!("pubmed: {e}"))?
            .json().await.map_err(|e| format!("pubmed parse: {e}"))?;
        if r.esearchresult.idlist.is_empty() {
            return Ok(format!("(no results for: {q})"));
        }
        Ok(format!("PMIDs: {}", r.esearchresult.idlist.join(", ")))
    }
}
