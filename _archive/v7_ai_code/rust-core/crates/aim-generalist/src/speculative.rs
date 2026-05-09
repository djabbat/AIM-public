//! Tiny speculative prefetch: when a tool_call references a path, we kick
//! off a parallel `read_file`-equivalent for the *next* likely paths
//! (siblings of the current path) and stash the bytes in a cache. The next
//! tool_call that asks for those paths gets an instant return.

use dashmap::DashMap;
use std::sync::Arc;

#[derive(Clone, Default)]
pub struct PrefetchCache {
    pub bytes: Arc<DashMap<String, Vec<u8>>>,
}

impl PrefetchCache {
    pub fn new() -> Self { Self { bytes: Arc::new(DashMap::new()) } }

    pub fn get(&self, path: &str) -> Option<Vec<u8>> {
        self.bytes.get(path).map(|r| r.clone())
    }

    /// Heuristic: when the model just called read_file on path `p`,
    /// preload its sibling files (same directory) up to 5 entries.
    pub fn schedule_siblings(&self, path: &str) {
        let cache = self.bytes.clone();
        let path_owned = path.to_string();
        tokio::spawn(async move {
            let p = std::path::Path::new(&path_owned);
            let Some(dir) = p.parent() else { return };
            let mut rd = match tokio::fs::read_dir(dir).await { Ok(r) => r, Err(_) => return };
            let mut count = 0;
            while let Ok(Some(entry)) = rd.next_entry().await {
                if count >= 5 { break; }
                let m = match entry.metadata().await { Ok(m) => m, Err(_) => continue };
                if !m.is_file() { continue; }
                if m.len() > 256 * 1024 { continue; }
                let entry_path = entry.path().to_string_lossy().into_owned();
                if cache.contains_key(&entry_path) { continue; }
                if let Ok(bytes) = tokio::fs::read(entry.path()).await {
                    cache.insert(entry_path, bytes);
                    count += 1;
                }
            }
        });
    }
}
