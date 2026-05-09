//! `aim-complexity` — task complexity classifier CLI.
//!
//!     aim-complexity classify "сравни A и B"
//!     aim-complexity classify "list files"

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 3 || args[1] != "classify" {
        eprintln!("usage: aim-complexity classify <task>");
        std::process::exit(2);
    }
    let task = args[2..].join(" ");
    let v = aim_complexity::classify(&task);
    match serde_json::to_string_pretty(&v) {
        Ok(s) => println!("{s}"),
        Err(e) => {
            eprintln!("[aim-complexity] json serialise failed: {e}");
            std::process::exit(1);
        }
    }
}
