"""Compare eval runs of a base (main) against a head (PR) and write a markdown report.

Each side can have several run files (repeats). Repeats matter because model output
varies run to run; averaging them keeps noise from blocking (or passing) a PR.

Usage:
  python -m evals.compare --base base_1.json base_2.json --head head_1.json head_2.json \
      --max-drop 0.04 --out report.md

Exit codes: 0 = pass (or no baseline), 1 = regression, 2 = error (API failures in a run).
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MAX_DROP = 0.04  # 4 points = 2 of 50 cases, about 3x the measured noise


@dataclass
class Side:
    runs: list

    @property
    def meta(self):
        return self.runs[0]["meta"] if self.runs else {}

    def case_ids(self):
        return set.intersection(*(set(c["id"] for c in r["cases"]) for r in self.runs)) if self.runs else set()

    def pass_fraction(self, case_id):
        """Share of runs in which this case passed (e.g. 2/3)."""
        hits = [c["passed"] for r in self.runs for c in r["cases"] if c["id"] == case_id]
        return sum(hits) / len(hits)

    def pass_rate(self, ids):
        if not self.runs or not ids:
            return 0.0
        return sum(self.pass_fraction(i) for i in ids) / len(ids)

    def agent_errors(self):
        return sum(r["summary"]["agent_errors"] for r in self.runs)


@dataclass
class Comparison:
    status: str          # "pass" | "regression" | "error" | "no_baseline"
    base_rate: float
    head_rate: float
    max_drop: float
    shared_ids: list
    regressions: list = field(default_factory=list)   # (id, base_frac, head_frac)
    improvements: list = field(default_factory=list)
    still_failing: list = field(default_factory=list)  # failed in every run on both sides
    added: list = field(default_factory=list)
    removed: list = field(default_factory=list)

    @property
    def delta(self):
        return self.head_rate - self.base_rate


def compare(base, head, max_drop=DEFAULT_MAX_DROP):
    head_ids, base_ids = head.case_ids(), base.case_ids()
    shared = sorted(head_ids & base_ids) if base.runs else sorted(head_ids)
    result = Comparison(
        status="pass",
        base_rate=base.pass_rate(shared),
        head_rate=head.pass_rate(shared),
        max_drop=max_drop,
        shared_ids=shared,
        added=sorted(head_ids - base_ids) if base.runs else [],
        removed=sorted(base_ids - head_ids),
    )
    if not base.runs:
        result.status = "no_baseline"
        return result

    for case_id in shared:
        b, h = base.pass_fraction(case_id), head.pass_fraction(case_id)
        if h < b:
            result.regressions.append((case_id, b, h))
        elif h > b:
            result.improvements.append((case_id, b, h))
        elif h == 0:
            result.still_failing.append(case_id)
    result.regressions.sort(key=lambda r: r[2] - r[1])  # biggest drop first

    if head.agent_errors() or base.agent_errors():
        result.status = "error"
    elif result.delta < -max_drop - 1e-9:
        result.status = "regression"
    return result


# --- markdown -------------------------------------------------------------------

HEADLINES = {
    "pass": "✅ **Eval passed**",
    "regression": "❌ **Eval failed: pass rate dropped more than the allowed threshold**",
    "error": "⚠️ **Eval errored: some API calls failed, so the scores are not trustworthy. Re-run the job.**",
    "no_baseline": "ℹ️ **No baseline on the target branch yet; showing this branch's results only**",
}


def _pct(x):
    return f"{x:.1%}"


def _frac(x, n):
    return f"{round(x * n)}/{n}"


def _case_index(side):
    return {c["id"]: c for c in side.runs[0]["cases"]} if side.runs else {}


def _category_rows(base, head, ids):
    cases = _case_index(head)
    rows = []
    for cat in sorted({cases[i]["category"] for i in ids}):
        cat_ids = [i for i in ids if cases[i]["category"] == cat]
        b = _pct(base.pass_rate(cat_ids)) if base.runs else "–"
        rows.append(f"| {cat} | {len(cat_ids)} | {b} | {_pct(head.pass_rate(cat_ids))} |")
    return rows


def _case_table(title, entries, base, head, cases):
    if not entries:
        return []
    nb, nh = len(base.runs), len(head.runs)
    lines = [f"### {title}", "", "| Case | Category | Base | Head | Question |", "|---|---|---|---|---|"]
    for case_id, b, h in entries:
        c = cases[case_id]
        lines.append(f"| {case_id} | {c['category']} | {_frac(b, nb)} | {_frac(h, nh)} | {c['question']} |")
    return lines + [""]


def render_markdown(result, base, head):
    cases = _case_index(head)
    bm, hm = base.meta, head.meta
    lines = [HEADLINES[result.status], ""]

    if base.runs:
        lines += [
            f"**Pass rate:** {_pct(result.base_rate)} → {_pct(result.head_rate)} "
            f"({result.delta * 100:+.1f} pts; fail if it drops more than {result.max_drop * 100:.0f} pts)",
            "",
        ]
    else:
        lines += [f"**Pass rate:** {_pct(result.head_rate)}", ""]

    lines += [
        "| | Base | Head |", "|---|---|---|",
        f"| Prompt | {bm.get('prompt_version', '–')} | {hm.get('prompt_version')} |",
        f"| Model | {bm.get('model', '–')} | {hm.get('model')} |",
        f"| Effort | {bm.get('effort', '–')} | {hm.get('effort')} |",
        f"| Runs | {len(base.runs)} | {len(head.runs)} |",
        f"| API errors | {base.agent_errors() if base.runs else '–'} | {head.agent_errors()} |",
        "",
    ]
    if result.added or result.removed:
        lines += [f"Test set changed: {len(result.shared_ids)} shared cases are compared "
                  f"(added: {', '.join(result.added) or 'none'}; removed: {', '.join(result.removed) or 'none'}).", ""]

    lines += ["### By category", "", "| Category | Cases | Base | Head |", "|---|---|---|---|"]
    lines += _category_rows(base, head, result.shared_ids) + [""]

    lines += _case_table("Regressions (passed less often than on base)", result.regressions, base, head, cases)
    lines += _case_table("Improvements", result.improvements, base, head, cases)
    if result.still_failing:
        lines += [f"**Failing on both:** {', '.join(result.still_failing)}", ""]
    if result.status == "no_baseline":
        failing = [i for i in result.shared_ids if head.pass_fraction(i) < 1]
        lines += [f"**Not passing every run:** {', '.join(failing) or 'none'}", ""]
    return "\n".join(lines)


# --- CLI -----------------------------------------------------------------------

EXIT_CODES = {"pass": 0, "no_baseline": 0, "regression": 1, "error": 2}


def load_runs(paths):
    return [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare base vs head eval runs.")
    parser.add_argument("--base", nargs="*", default=[], help="base (main) run files; may be empty")
    parser.add_argument("--head", nargs="+", required=True, help="head (PR) run files")
    parser.add_argument("--max-drop", type=float, default=DEFAULT_MAX_DROP,
                        help="largest allowed pass-rate drop, as a fraction (0.04 = 4 points)")
    parser.add_argument("--out", type=Path, help="write the markdown report here")
    args = parser.parse_args(argv)

    base, head = Side(load_runs(args.base)), Side(load_runs(args.head))
    result = compare(base, head, args.max_drop)
    report = render_markdown(result, base, head)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
    print(report)
    return EXIT_CODES[result.status]


if __name__ == "__main__":
    sys.exit(main())
