"""Grader 2: does the generated SQL return the same result set as the gold SQL?

Matching rules (from CLAUDE.md):
  * Compare result values, never SQL text or column names.
  * Ignore row order unless order_matters is True.
  * Round numbers to 4 decimal places; ints and floats compare equal (5 == 5.0).
  * Duplicate rows count: [1, 1, 2] does NOT match [1, 2].
  * Column order matters: (a, b) does not match (b, a).
  * A query that errors or times out fails.
"""

from collections import Counter
from dataclasses import dataclass

from evals.graders.executes import DEFAULT_TIMEOUT_S, run_sql

FLOAT_DECIMALS = 4


@dataclass
class MatchResult:
    passed: bool
    reason: str  # "match", "pred_error: ...", "gold_error: ...", "row_count_mismatch", "value_mismatch"


def normalize_value(value):
    """Numbers -> float rounded to 4 dp. Everything else (str, None, bytes) unchanged."""
    if isinstance(value, (int, float)):
        return round(float(value), FLOAT_DECIMALS)
    return value


def normalize_row(row):
    return tuple(normalize_value(v) for v in row)


def results_match(pred_rows, gold_rows, order_matters=False):
    """True if the two row lists hold the same values."""
    pred = [normalize_row(r) for r in pred_rows]
    gold = [normalize_row(r) for r in gold_rows]
    if order_matters:
        return pred == gold
    # Counter = multiset: ignores order but keeps duplicate counts.
    return Counter(pred) == Counter(gold)


def exec_match(pred_sql, gold_sql, db_path, order_matters=False, timeout_s=DEFAULT_TIMEOUT_S):
    """Run both queries and compare. Returns a MatchResult with a reason."""
    gold = run_sql(gold_sql, db_path, timeout_s)
    if not gold.ok:
        return MatchResult(False, f"gold_error: {gold.error}")
    pred = run_sql(pred_sql, db_path, timeout_s)
    if not pred.ok:
        return MatchResult(False, f"pred_error: {pred.error}")
    if results_match(pred.rows, gold.rows, order_matters):
        return MatchResult(True, "match")
    if len(pred.rows) != len(gold.rows):
        return MatchResult(False, "row_count_mismatch")
    return MatchResult(False, "value_mismatch")
