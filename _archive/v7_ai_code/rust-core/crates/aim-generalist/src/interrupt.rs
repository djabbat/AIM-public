//! Cooperative interrupt registry. Each `Runner::run*` allocates a `run_id`
//! + `AtomicBool` flag. POST /v1/interrupt/:run_id flips the flag; the
//! ReAct loop checks at the top of every iteration and bails out cleanly.

use dashmap::DashMap;
use std::sync::atomic::AtomicBool;
use std::sync::Arc;

#[derive(Clone, Default)]
pub struct InterruptRegistry {
    pub flags: Arc<DashMap<String, Arc<AtomicBool>>>,
}

impl InterruptRegistry {
    pub fn new() -> Self { Self { flags: Arc::new(DashMap::new()) } }

    pub fn register(&self, run_id: String) -> Arc<AtomicBool> {
        let flag = Arc::new(AtomicBool::new(false));
        self.flags.insert(run_id, flag.clone());
        flag
    }

    pub fn signal(&self, run_id: &str) -> bool {
        if let Some(f) = self.flags.get(run_id) {
            f.store(true, std::sync::atomic::Ordering::SeqCst);
            true
        } else { false }
    }

    pub fn release(&self, run_id: &str) {
        self.flags.remove(run_id);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::Ordering;

    #[test]
    fn registry_register_and_signal() {
        let reg = InterruptRegistry::new();
        let flag = reg.register("run-1".to_string());
        assert!(!flag.load(Ordering::SeqCst));
        reg.signal("run-1");
        assert!(flag.load(Ordering::SeqCst));
    }

    #[test]
    fn registry_signal_unknown_run_returns_false() {
        let reg = InterruptRegistry::new();
        assert!(!reg.signal("does-not-exist"));
    }

    #[test]
    fn registry_release_drops_flag() {
        let reg = InterruptRegistry::new();
        let _f = reg.register("run-x".to_string());
        reg.release("run-x");
        assert!(!reg.signal("run-x"));
        // Re-register should give fresh, un-set flag
        let f2 = reg.register("run-x".to_string());
        assert!(!f2.load(Ordering::SeqCst));
    }
}
