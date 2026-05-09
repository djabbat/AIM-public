use crate::Result;
use r2d2::Pool;
use r2d2_sqlite::SqliteConnectionManager;
use std::path::Path;

pub type DbPool = Pool<SqliteConnectionManager>;

pub fn open_pool(db_path: &Path) -> Result<DbPool> {
    if let Some(parent) = db_path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let manager = SqliteConnectionManager::file(db_path).with_init(|c| {
        c.execute_batch(
            "PRAGMA journal_mode=WAL;
             PRAGMA synchronous=NORMAL;
             PRAGMA foreign_keys=ON;
             PRAGMA busy_timeout=2000;
             PRAGMA cache_size=-8000;",
        )
    });
    let pool = Pool::builder().max_size(3).build(manager)?;
    init_schema(&pool)?;
    Ok(pool)
}

const INIT_SQL: &str = include_str!("../migrations/001_init.sql");

fn init_schema(pool: &DbPool) -> Result<()> {
    let conn = pool.get()?;
    conn.execute_batch(INIT_SQL)?;
    Ok(())
}
