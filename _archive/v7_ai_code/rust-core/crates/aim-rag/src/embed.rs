//! Embedding client. Default: Gemini text-embedding-004 (free tier).
//! Set AIM_EMBED_PROVIDER=hash for deterministic stub (CI / no-network).

use serde::Deserialize;
use serde_json::json;

pub struct Embedder {
    backend: Backend,
    client: reqwest::Client,
}

enum Backend {
    Gemini { api_key: String, model: String },
    Hash,
}

impl Embedder {
    pub fn from_env() -> Self {
        let backend = match std::env::var("AIM_EMBED_PROVIDER").as_deref() {
            Ok("hash") => Backend::Hash,
            _ => match std::env::var("GEMINI_API_KEY") {
                Ok(k) if !k.is_empty() => Backend::Gemini {
                    api_key: k,
                    model: std::env::var("AIM_EMBED_MODEL")
                        .unwrap_or_else(|_| "text-embedding-004".into()),
                },
                _ => Backend::Hash,
            },
        };
        Self {
            backend,
            client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(60))
                .build()
                .expect("reqwest"),
        }
    }

    pub async fn embed_one(&self, text: &str) -> anyhow::Result<Vec<f32>> {
        Ok(self.embed_batch(&[text.to_string()]).await?.into_iter().next().unwrap())
    }

    pub async fn embed_batch(&self, texts: &[String]) -> anyhow::Result<Vec<Vec<f32>>> {
        use futures::stream::{self, StreamExt};

        match &self.backend {
            Backend::Hash => Ok(texts.iter().map(|t| hash_embed(t, 256)).collect()),
            Backend::Gemini { api_key, model } => {
                let concurrency: usize = std::env::var("AIM_EMBED_CONCURRENCY")
                    .ok().and_then(|s| s.parse().ok()).unwrap_or(8);

                let owned: Vec<String> = texts.to_vec();
                let key = api_key.clone();
                let m = model.clone();
                let client = self.client.clone();

                let results: Vec<anyhow::Result<Vec<f32>>> = stream::iter(owned)
                    .map(move |t| {
                        let key = key.clone();
                        let m = m.clone();
                        let client = client.clone();
                        async move { gemini_call(&client, &key, &m, &t).await }
                    })
                    .buffer_unordered(concurrency.max(1))
                    .collect()
                    .await;
                results.into_iter().collect()
            }
        }
    }
}

async fn gemini_call(
    client: &reqwest::Client,
    key: &str,
    model: &str,
    text: &str,
) -> anyhow::Result<Vec<f32>> {
    let url = format!(
        "https://generativelanguage.googleapis.com/v1beta/models/{}:embedContent?key={}",
        model, key
    );
    let resp: GemResp = client.post(&url)
        .json(&json!({
            "model": format!("models/{}", model),
            "content": { "parts": [{ "text": text }] }
        }))
        .send().await?
        .error_for_status()?
        .json().await?;
    Ok(resp.embedding.values)
}

#[derive(Deserialize)] struct GemResp { embedding: GemEmbed }
#[derive(Deserialize)] struct GemEmbed { values: Vec<f32> }

/// Deterministic hashed bag-of-tokens embedding. Useful for tests + offline.
fn hash_embed(text: &str, dim: usize) -> Vec<f32> {
    let mut v = vec![0f32; dim];
    for tok in text.split_whitespace() {
        let h = fxhash(tok) as usize;
        let i = h % dim;
        v[i] += 1.0;
    }
    let norm: f32 = v.iter().map(|x| x * x).sum::<f32>().sqrt().max(1e-9);
    for x in &mut v { *x /= norm; }
    v
}

fn fxhash(s: &str) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    for b in s.bytes() {
        h ^= b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    h
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hash_embed_fixed_dimension() {
        let v = hash_embed("hello world", 256);
        assert_eq!(v.len(), 256);
    }

    #[test]
    fn hash_embed_deterministic() {
        let a = hash_embed("aim integrative", 128);
        let b = hash_embed("aim integrative", 128);
        assert_eq!(a, b);
    }

    #[test]
    fn hash_embed_distinct_inputs_distinct_outputs() {
        let a = hash_embed("alpha", 64);
        let b = hash_embed("beta", 64);
        assert_ne!(a, b);
    }

    #[test]
    fn fxhash_stability() {
        // Two calls — same hash.
        assert_eq!(fxhash("AIM"), fxhash("AIM"));
        assert_ne!(fxhash("AIM"), fxhash("aim"));
    }

    #[tokio::test]
    async fn embed_one_via_hash_backend() {
        std::env::set_var("AIM_EMBED_PROVIDER", "hash");
        let e = Embedder::from_env();
        let v = e.embed_one("hello").await.expect("must succeed");
        assert!(!v.is_empty());
    }
}
