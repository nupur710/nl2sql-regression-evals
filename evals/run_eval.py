"""Run the SQL agent over the golden set and write a results JSON.

Usage:
  python -m evals.run_eval                        # prompt v1, all cases
  python -m evals.run_eval --prompt v2            # a different prompt version
  python -m evals.run_eval --limit 3              # first 3 cases (cheap smoke test)
  python -m evals.run_eval --out results/x.json   # choose the output file
"""

import argparse
import hashlib
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from data.seed import DEFAULT_DB_PATH, build_db
from evals.graders.exec_match import exec_match
from evals.graders.executes import executes

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = ROOT / "data" / "golden.jsonl"
RESULTS_DIR = ROOT / "results"


def load_golden(path=GOLDEN_PATH):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


# --- one case ----------------------------------------------------------------

def grade(case, pred_sql, db_path):
    match = exec_match(pred_sql, case["gold_sql"], db_path, case["order_matters"])
    return {
        "executes": executes(pred_sql, db_path),
        "passed": match.passed,
        "reason": match.reason,
    }


def run_case(case, agent, db_path):
    record = {key: case[key] for key in ("id", "category", "difficulty", "question", "gold_sql")}
    try:
        result = agent.generate_sql(case["question"])
    except Exception as exc:  # one failed API call must not kill the whole run
        record.update(pred_sql=None, executes=False, passed=False,
                      reason=f"agent_error: {type(exc).__name__}: {exc}")
        return record

    record.update(
        pred_sql=result.sql,
        stop_reason=result.stop_reason,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        latency_s=result.latency_s,
    )
    record.update(grade(case, result.sql, db_path))
    return record


# --- whole run ----------------------------------------------------------------

def evaluate(cases, agent, db_path, verbose=False, workers=1):
    """Run every case. workers > 1 runs API calls in parallel threads
    (each grader call opens its own SQLite connection, so this is safe)."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        records = list(pool.map(lambda case: run_case(case, agent, db_path), cases))
    if verbose:
        for record in records:
            status = "PASS" if record["passed"] else "FAIL"
            print(f"  {record['id']}  {status}  {record['reason']}")
    return records


def _rate(records, key):
    return round(sum(r[key] for r in records) / len(records), 4) if records else 0.0


def _breakdown(records, field):
    groups = defaultdict(list)
    for r in records:
        groups[r[field]].append(r)
    return {
        name: {"n": len(rs), "passed": sum(r["passed"] for r in rs), "pass_rate": _rate(rs, "passed")}
        for name, rs in sorted(groups.items())
    }


def summarize(records):
    return {
        "n_cases": len(records),
        "passed": sum(r["passed"] for r in records),
        "pass_rate": _rate(records, "passed"),
        "executes_rate": _rate(records, "executes"),
        # Infrastructure failures (network, auth, rate limit). A run with these
        # is not a fair measure of the agent; the CI gate will treat it separately.
        "agent_errors": sum(r["reason"].startswith("agent_error") for r in records),
        "by_category": _breakdown(records, "category"),
        "by_difficulty": _breakdown(records, "difficulty"),
        "input_tokens": sum(r.get("input_tokens", 0) for r in records),
        "output_tokens": sum(r.get("output_tokens", 0) for r in records),
    }


def print_summary(summary):
    print(f"\nPass rate: {summary['passed']}/{summary['n_cases']} = {summary['pass_rate']:.1%}"
          f"   (executes: {summary['executes_rate']:.1%}, agent errors: {summary['agent_errors']})")
    for title, key in (("category", "by_category"), ("difficulty", "by_difficulty")):
        print(f"By {title}:")
        for name, s in summary[key].items():
            print(f"  {name:<14} {s['passed']}/{s['n']}")
    print(f"Tokens: {summary['input_tokens']} in, {summary['output_tokens']} out")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the SQL agent over the golden set.")
    parser.add_argument("--prompt", default="v1", help="prompt version in agent/prompts/")
    parser.add_argument("--limit", type=int, help="only run the first N cases")
    parser.add_argument("--out", type=Path, help="results JSON path (default: results/<time>_<prompt>.json)")
    parser.add_argument("--workers", type=int, default=5, help="parallel API calls (default 5)")
    args = parser.parse_args(argv)

    from agent.sql_agent import SQLAgent  # imported here so tests don't need the SDK client

    cases = load_golden()[: args.limit]
    db_path = build_db(DEFAULT_DB_PATH)  # fresh, identical db every run
    agent = SQLAgent(prompt_version=args.prompt)

    started = datetime.now(timezone.utc)
    print(f"Running {len(cases)} cases | prompt={agent.prompt_version} "
          f"model={agent.model} effort={agent.effort}")
    records = evaluate(cases, agent, db_path, verbose=True, workers=args.workers)
    summary = summarize(records)

    meta = {
        "run_at": started.isoformat(timespec="seconds"),
        "prompt_version": agent.prompt_version,
        "model": agent.model,
        "effort": agent.effort,
        "golden_sha256": file_sha256(GOLDEN_PATH),
    }
    out = args.out or RESULTS_DIR / f"{started:%Y%m%d-%H%M%S}_{agent.prompt_version}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"meta": meta, "summary": summary, "cases": records}, indent=2),
                   encoding="utf-8")

    print_summary(summary)
    print(f"Results written to {out}")


if __name__ == "__main__":
    main()
