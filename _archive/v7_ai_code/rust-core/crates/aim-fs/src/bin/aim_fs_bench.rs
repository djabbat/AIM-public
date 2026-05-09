//! aim-fs-bench — verify SMART metrics from SPEC §11.
//!
//! Goals (per SPEC v11):
//!   * propose+approve p95 latency < 500 ms
//!   * propose throughput > 100 ops/s on a single-user dev machine
//!   * sweeper latency < 200 ms on 1 000 entities
//!   * search p95 < 100 ms on 10⁴ entities
//!
//! Runs against a fresh temp aim_root (no contamination of user data).
//!
//! Usage:
//!     aim-fs-bench [--n 1000] [--concurrency 4] [--keep]
use aim_fs::{
    search::SearchScope, sweeper, Actor, AimFs, ApprovalPolicy, NewEntity, Source,
};
use std::path::PathBuf;
use std::sync::Arc;
use std::thread;
use std::time::Instant;

fn main() -> anyhow::Result<()> {
    let mut n: usize = 1000;
    let mut concurrency: usize = 4;
    let mut keep = false;

    let argv: Vec<String> = std::env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        match argv[i].as_str() {
            "-h" | "--help" => {
                println!("aim-fs-bench [--n 1000] [--concurrency 4] [--keep]");
                return Ok(());
            }
            "--n" => {
                n = argv[i + 1].parse()?;
                i += 2;
            }
            "--concurrency" => {
                concurrency = argv[i + 1].parse()?;
                i += 2;
            }
            "--keep" => {
                keep = true;
                i += 1;
            }
            other => anyhow::bail!("unknown arg: {other}"),
        }
    }

    let dir = tempfile::tempdir()?;
    let root: PathBuf = dir.path().to_path_buf();
    println!("→ aim_root: {}", root.display());

    let fs = Arc::new(AimFs::open(&root)?);
    let policy = Arc::new(default_policy());
    let tenant = "djabbat";

    println!("\n# Benchmark: propose ({n} ops, concurrency={concurrency})");
    let propose_lats = run_propose(fs.clone(), policy.clone(), tenant, n, concurrency);
    print_stats("propose latency (µs)", &propose_lats);
    let total_us: u128 = propose_lats.iter().sum();
    let throughput = (n as f64) / ((total_us as f64) / 1_000_000.0)
        * (concurrency as f64).min(1.0).max(1.0);
    println!(
        "  throughput (single-pool, sequential):  {:.1} ops/s",
        n as f64 / propose_lats.iter().sum::<u128>().max(1) as f64 * (concurrency as f64) * 1_000_000.0
    );
    let _ = total_us;
    let _ = throughput;

    println!("\n# Benchmark: search ({n} ops on populated DB)");
    let search_lats = run_search(fs.clone(), tenant, n);
    print_stats("search latency (µs)", &search_lats);

    println!("\n# Benchmark: sweeper (one full pass on populated DB)");
    let s = Instant::now();
    let pool = get_pool(&fs);
    let n_changed = sweeper::sweep_once(&pool)?;
    let sweep_us = s.elapsed().as_micros();
    println!(
        "  sweep_once → {} status changes in {} µs ({:.1} ms)",
        n_changed,
        sweep_us,
        (sweep_us as f64) / 1000.0
    );

    println!("\n# Benchmark: approve ({} of {} proposals)", concurrency * 100, n);
    // Build a fresh batch of pending proposals to approve.
    let mut approve_lats = Vec::new();
    let pending = fs.list_pending(tenant, 10_000)?;
    let actor = Actor {
        user_id: tenant.into(),
        session_id: None,
    };
    for p in pending.iter().take(concurrency * 100) {
        let s = Instant::now();
        if fs.approve_proposal(tenant, &p.id, &actor).is_ok() {
            approve_lats.push(s.elapsed().as_micros());
        }
    }
    print_stats("approve latency (µs)", &approve_lats);

    if keep {
        std::mem::forget(dir);
        println!("\n--keep: tempdir retained at {}", root.display());
    }

    Ok(())
}

fn run_propose(
    fs: Arc<AimFs>,
    policy: Arc<ApprovalPolicy>,
    tenant: &'static str,
    n: usize,
    concurrency: usize,
) -> Vec<u128> {
    let chunk = (n + concurrency - 1) / concurrency;
    let mut handles = vec![];
    for w in 0..concurrency {
        let fs = fs.clone();
        let policy = policy.clone();
        let lo = w * chunk;
        let hi = ((w + 1) * chunk).min(n);
        let h = thread::spawn(move || {
            let mut lats = Vec::with_capacity(hi - lo);
            for i in lo..hi {
                let entity = bench_entity(tenant, i);
                let s = Instant::now();
                let _ = fs.propose(tenant, entity, None, None, &policy);
                lats.push(s.elapsed().as_micros());
            }
            lats
        });
        handles.push(h);
    }
    handles
        .into_iter()
        .flat_map(|h| h.join().unwrap_or_default())
        .collect()
}

fn run_search(fs: Arc<AimFs>, tenant: &str, n: usize) -> Vec<u128> {
    let queries = ["fact", "ze", "deepseek", "patient", "alpha"];
    let mut lats = Vec::with_capacity(n);
    for i in 0..n {
        let q = queries[i % queries.len()];
        let s = Instant::now();
        let _ = fs.search(tenant, q, &SearchScope::default(), 10);
        lats.push(s.elapsed().as_micros());
    }
    lats
}

fn print_stats(label: &str, lats: &[u128]) {
    if lats.is_empty() {
        println!("  {label}: (no samples)");
        return;
    }
    let mut s: Vec<u128> = lats.to_vec();
    s.sort();
    let n = s.len();
    let mean = (s.iter().sum::<u128>() as f64) / (n as f64);
    let p50 = s[n / 2];
    let p95 = s[(n * 95) / 100];
    let p99 = s[(n * 99) / 100];
    let max = *s.last().unwrap();
    println!(
        "  {label}: n={n}  mean={:.0}  p50={}  p95={}  p99={}  max={}",
        mean, p50, p95, p99, max
    );
}

fn bench_entity(tenant: &str, i: usize) -> NewEntity {
    NewEntity {
        schema: "feedback_v1".into(),
        schema_version: 1,
        title: Some(format!("bench feedback {i}")),
        description: Some("benchmark entity".into()),
        body: Some(format!(
            "**Why:** benchmark synthetic entity #{i}\n\
             **How to apply:** workload generator only\n\n\
             body content for ze patient deepseek alpha fact"
        )),
        source: Source::System,
        user_id: tenant.to_string(),
        session_id: None,
        llm_model: None,
        confidence: Some(0.5),
        requires_verification: false,
        scope_global: false,
        scope_user_ids: vec![tenant.to_string()],
        scope_project_ids: None,
        scope_patient_ids: vec![],
        tags: vec!["bench".into(), format!("g{}", i % 10)],
        decay_ttl_days: None,
        decay_on_expire: None,
        initial_links: vec![],
    }
}

fn default_policy() -> ApprovalPolicy {
    ApprovalPolicy {
        auto_approve_user_commands: true,
        auto_approve_observational_with_confidence_above: 0.95,
        auto_approve_service_events: true,
        require_approval_for: vec!["feedback".into()],
        max_inactivity_days: 30,
    }
}

// Re-export of pool through a bench helper. We can't access fs.pool directly
// (pub(crate)), but we can re-open from disk — cheap given WAL.
fn get_pool(fs: &AimFs) -> aim_fs::db::DbPool {
    let db = fs.root().join("_service").join("db").join("aim_fs.db");
    aim_fs::db::open_pool(&db).expect("reopen pool for sweeper bench")
}
