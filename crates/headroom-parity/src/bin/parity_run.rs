//! `parity-run` CLI: drive the parity harness from the command line.

use anyhow::Result;
use clap::{Parser, Subcommand};
use headroom_parity::{builtin_comparators, run_comparator};
use std::path::PathBuf;

#[derive(Parser, Debug)]
#[command(
    name = "parity-run",
    about = "Run Headroom Rust-vs-Python parity checks"
)]
struct Cli {
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand, Debug)]
enum Cmd {
    /// Run all built-in comparators against fixtures under --fixtures.
    Run {
        #[arg(long, default_value = "tests/parity/fixtures")]
        fixtures: PathBuf,
        /// Only run this comparator (by transform name).
        #[arg(long)]
        only: Option<String>,
    },
    /// List the transforms the harness knows about.
    List,
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.cmd {
        Cmd::List => {
            for c in builtin_comparators() {
                println!("{}", c.name());
            }
            Ok(())
        }
        Cmd::Run { fixtures, only } => {
            let mut any_diffs = false;
            let mut any_skipped = false;
            // Track total fixtures compared across all run comparators so a
            // missing/empty/typo'd fixtures dir (total==0) cannot pass green.
            let mut grand_total = 0usize;
            let mut ran_any_comparator = false;
            for comparator in builtin_comparators() {
                if let Some(ref filt) = only {
                    if filt != comparator.name() {
                        continue;
                    }
                }
                ran_any_comparator = true;
                let report = run_comparator(&fixtures, comparator.as_ref())?;
                grand_total += report.total();
                println!(
                    "[{:<16}] total={} matched={} skipped={} diffed={}",
                    comparator.name(),
                    report.total(),
                    report.matched,
                    report.skipped.len(),
                    report.diffed.len()
                );
                for (path, reason) in &report.skipped {
                    any_skipped = true;
                    println!("  skipped {}: {}", path.display(), reason);
                }
                for (path, expected, actual) in &report.diffed {
                    any_diffs = true;
                    println!("  DIFF {}", path.display());
                    println!("    expected: {}", first_line(expected));
                    println!("    actual  : {}", first_line(actual));
                }
            }
            // Fail-closed parity gate: an explicit diff, any skipped fixture
            // (comparator bailed/panicked -> proves nothing), zero fixtures
            // compared (missing/empty/typo'd fixtures dir), or an --only filter
            // that matched no comparator must all exit non-zero. A green exit
            // requires we actually compared >=1 fixture and every one matched.
            if any_diffs {
                eprintln!("parity FAILED: at least one fixture diffed");
                std::process::exit(1);
            }
            if any_skipped {
                eprintln!(
                    "parity FAILED: at least one fixture was SKIPPED (comparator error); \
                     a skipped fixture proves nothing, so the gate is fail-closed"
                );
                std::process::exit(1);
            }
            if !ran_any_comparator {
                eprintln!("parity FAILED: --only filter matched no known comparator");
                std::process::exit(1);
            }
            if grand_total == 0 {
                eprintln!(
                    "parity FAILED: compared ZERO fixtures (missing/empty/typo'd fixtures dir); \
                     refusing to pass vacuously"
                );
                std::process::exit(1);
            }
            Ok(())
        }
    }
}

fn first_line(s: &str) -> String {
    s.lines().next().unwrap_or("").to_string()
}
