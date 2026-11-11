"""How often does the LLM judge agree with execution grading, and where is it fooled?

Items to judge come from two sources:
  * traps (default): for every golden case, its gold SQL (correct) and its known-wrong
    trap query (incorrect), from data/trap_queries.jsonl. 100 items, half right, half
    wrong, so agreement isn't inflated by a set that is almost all correct.
  * --results FILE: the SQL the agent actually wrote in an eval run.

Every item's true label comes from execution grading (exec_match against gold).

Usage:
  python -m evals.judge_agreement                       # trap set, default judge
  python -m evals.judge_agreement --limit 5             # cheap smoke test (10 items)
  python -m evals.judge_agreement --results results/x.json --no-traps
"""

import argparse
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from data.seed import DEFAULT_DB_PATH, build_db
from evals.graders.exec_match import exec_match
from evals.run_eval import GOLDEN_PATH, RESULTS_DIR, ROOT, load_golden

TRAPS_PATH = ROOT / "data" / "trap_queries.jsonl"
REPORTS_DIR = ROOT / "reports"


# --- building labelled items -------------------------------------------------------

def _item(case, source, sql):
    return {"item_id": f"{case['id']}:{source}", "case_id": case["id"], "source": source,
            "category": case["category"], "difficulty": case["difficulty"],
            "question": case["question"], "sql": sql}


def trap_items(cases, traps_path=TRAPS_PATH):
    traps = {}
    with open(traps_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                traps[row["id"]] = row
    items = []
    for case in cases:
        items.append(_item(case, "gold", case["gold_sql"]))
        if case["id"] in traps:
            items.append(_item(case, "trap", traps[case["id"]]["wrong_sql"]))
    return items


def result_items(results_path, cases):
    by_id = {c["id"]: c for c in cases}
    run = json.loads(Path(results_path).read_text(encoding="utf-8"))
    return [_item(by_id[r["id"]], "agent", r["pred_sql"])
            for r in run["cases"] if r.get("pred_sql") and r["id"] in by_id]


def label_items(items, cases, db_path):
    """Attach the execution-grading label (the source of truth) to each item."""
    by_id = {c["id"]: c for c in cases}
    for item in items:
        case = by_id[item["case_id"]]
        match = exec_match(item["sql"], case["gold_sql"], db_path, case["order_matters"])
        item["exec_pass"], item["exec_reason"] = match.passed, match.reason
    return items


def judge_items(items, judge, workers=5):
    def run(item):
        try:
            verdict = judge.judge(item["question"], item["sql"])
            return {**item, "judge_correct": verdict.correct, "judge_reasoning": verdict.reasoning,
                    "judge_model": verdict.model, "input_tokens": verdict.input_tokens,
                    "output_tokens": verdict.output_tokens}
        except Exception as exc:  # one API failure shouldn't kill the analysis
            return {**item, "judge_correct": None,
                    "judge_reasoning": f"judge_error: {type(exc).__name__}: {exc}"}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run, items))


# --- metrics -------------------------------------------------------------------------

def confusion(items):
    """Positive = 'correct'. Only items with a judge verdict are counted."""
    counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for it in items:
        if it["judge_correct"] is None:
            continue
        key = ("t" if it["exec_pass"] == it["judge_correct"] else "f") + \
              ("p" if it["judge_correct"] else "n")
        counts[key] += 1
    return counts


def cohens_kappa(tp, fp, fn, tn):
    """Agreement corrected for chance. 1 = perfect, 0 = no better than chance.
    None when undefined (both raters gave the same single label to everything)."""
    n = tp + fp + fn + tn
    if n == 0:
        return None
    observed = (tp + tn) / n
    judge_yes, exec_yes = (tp + fp) / n, (tp + fn) / n
    expected = judge_yes * exec_yes + (1 - judge_yes) * (1 - exec_yes)
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


def _ratio(num, den):
    return num / den if den else None


def summarize(items):
    c = confusion(items)
    judged = sum(c.values())
    by_cat = defaultdict(list)
    for it in items:
        if it["judge_correct"] is not None:
            by_cat[it["category"]].append(it["exec_pass"] == it["judge_correct"])
    return {
        "n_items": len(items),
        "judged": judged,
        "no_verdict": len(items) - judged,
        "accuracy": _ratio(c["tp"] + c["tn"], judged),
        "kappa": cohens_kappa(**c),
        "confusion": c,
        # Of the queries that are actually WRONG, how many did the judge pass? (fooled)
        "false_pass_rate": _ratio(c["fp"], c["fp"] + c["tn"]),
        # Of the queries that are actually RIGHT, how many did the judge reject?
        "false_fail_rate": _ratio(c["fn"], c["tp"] + c["fn"]),
        "accuracy_by_category": {k: _ratio(sum(v), len(v)) for k, v in sorted(by_cat.items())},
        "input_tokens": sum(it.get("input_tokens", 0) for it in items),
        "output_tokens": sum(it.get("output_tokens", 0) for it in items),
    }


# --- report ----------------------------------------------------------------------------

def _fmt(x, pct=True):
    if x is None:
        return "n/a"
    return f"{x:.1%}" if pct else f"{x:.3f}"


def render_markdown(summary, items, meta):
    c = summary["confusion"]
    fooled = [it for it in items if it["judge_correct"] is True and not it["exec_pass"]]
    rejected = [it for it in items if it["judge_correct"] is False and it["exec_pass"]]
    no_verdict = [it for it in items if it["judge_correct"] is None]

    lines = [
        "# LLM judge vs execution grading", "",
        f"Judge: `{meta['judge_model']}` (effort `{meta['judge_effort']}`, prompt `{meta['judge_prompt']}`). "
        f"Items: {summary['n_items']} ({meta['sources']}). Run: {meta['run_at']}.", "",
        "| Metric | Value |", "|---|---|",
        f"| Accuracy (agreement with execution) | {_fmt(summary['accuracy'])} |",
        f"| Cohen's kappa | {_fmt(summary['kappa'], pct=False)} |",
        f"| Fooled: wrong SQL judged correct | {c['fp']} of {c['fp'] + c['tn']} ({_fmt(summary['false_pass_rate'])}) |",
        f"| Too strict: right SQL judged wrong | {c['fn']} of {c['tp'] + c['fn']} ({_fmt(summary['false_fail_rate'])}) |",
        f"| No verdict | {summary['no_verdict']} |", "",
        "|  | Execution: correct | Execution: wrong |", "|---|---|---|",
        f"| **Judge: correct** | {c['tp']} | {c['fp']} |",
        f"| **Judge: wrong** | {c['fn']} | {c['tn']} |", "",
        "### Accuracy by category", "", "| Category | Accuracy |", "|---|---|",
    ]
    lines += [f"| {k} | {_fmt(v)} |" for k, v in summary["accuracy_by_category"].items()] + [""]

    def table(title, rows):
        if not rows:
            return [f"### {title}", "", "None.", ""]
        out = [f"### {title}", "", "| Item | Category | Execution says | Judge's reasoning |", "|---|---|---|---|"]
        for it in rows:
            reason = it["judge_reasoning"].replace("|", "\\|").replace("\n", " ")
            out.append(f"| {it['item_id']} | {it['category']} | {it['exec_reason']} | {reason} |")
        return out + [""]

    lines += table("Where the judge was fooled (wrong SQL it passed)", fooled)
    lines += table("Where the judge was too strict (right SQL it failed)", rejected)
    if no_verdict:
        lines += table("No verdict", no_verdict)
    return "\n".join(lines)


# --- CLI ---------------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Measure LLM judge agreement with execution grading.")
    parser.add_argument("--results", nargs="*", default=[], help="eval run files whose agent SQL to judge")
    parser.add_argument("--no-traps", action="store_true", help="don't include the gold/trap item set")
    parser.add_argument("--limit", type=int, help="only use the first N golden cases")
    parser.add_argument("--prompt", default="v1", help="judge prompt version")
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--out", type=Path, help="markdown report path (default: reports/judge_agreement_<model>.md)")
    args = parser.parse_args(argv)

    from evals.graders.llm_judge import LLMJudge  # here so tests don't need an API client

    cases = load_golden(GOLDEN_PATH)[: args.limit]
    items, sources = [], []
    if not args.no_traps:
        items += trap_items(cases)
        sources.append("gold + trap queries")
    for path in args.results:
        items += result_items(path, cases)
        sources.append(f"agent SQL from {Path(path).name}")

    db_path = build_db(DEFAULT_DB_PATH)
    label_items(items, cases, db_path)
    judge = LLMJudge(prompt_version=args.prompt)
    print(f"Judging {len(items)} items with {judge.model} (effort {judge.effort})...")
    items = judge_items(items, judge, workers=args.workers)
    summary = summarize(items)

    started = datetime.now(timezone.utc)
    meta = {"run_at": started.isoformat(timespec="seconds"), "judge_model": judge.model,
            "judge_effort": judge.effort, "judge_prompt": args.prompt, "sources": "; ".join(sources)}
    report = render_markdown(summary, items, meta)

    out = args.out or REPORTS_DIR / f"judge_agreement_{judge.model}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    raw = RESULTS_DIR / f"{started:%Y%m%d-%H%M%S}_judge_{judge.model}.json"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(json.dumps({"meta": meta, "summary": summary, "items": items}, indent=2), encoding="utf-8")

    print(report)
    print(f"\nReport: {out}\nRaw items: {raw}")


if __name__ == "__main__":
    main()
