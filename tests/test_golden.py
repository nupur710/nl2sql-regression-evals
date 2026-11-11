"""Checks on the golden test cases themselves.

A bad golden case silently corrupts every eval run, so we verify that:
  1. every case is well-formed,
  2. every gold query runs and returns rows,
  3. each trap really bites: a known-wrong query FAILS the case,
  4. a differently-written correct query PASSES the case.

The wrong and alternative queries live in data/trap_queries.jsonl; the LLM judge
agreement analysis reuses them as labelled examples.
"""

import json
from pathlib import Path

import pytest

from evals.graders.exec_match import exec_match
from evals.graders.executes import run_sql

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
GOLDEN_PATH = DATA_DIR / "golden.jsonl"
TRAPS_PATH = DATA_DIR / "trap_queries.jsonl"
REQUIRED_FIELDS = {"id", "question", "gold_sql", "category", "difficulty", "order_matters", "notes"}
CATEGORIES = {"join", "aggregation", "null_handling", "ambiguity", "date", "trap"}
DIFFICULTIES = {"easy", "medium", "hard"}


def load_jsonl(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_golden():
    return load_jsonl(GOLDEN_PATH)


CASES = {case["id"]: case for case in load_golden()}
TRAPS = {row["id"]: row for row in load_jsonl(TRAPS_PATH)}
# A plausible mistake for each case. Each must NOT match gold.
WRONG_SQL = {cid: row["wrong_sql"] for cid, row in TRAPS.items()}
# A correct query written differently from gold. Each MUST match gold.
ALT_CORRECT_SQL = {cid: row["alt_sql"] for cid, row in TRAPS.items() if "alt_sql" in row}


def test_golden_has_fifty_unique_cases():
    cases = load_golden()
    assert len(cases) == 50
    assert len(CASES) == 50  # ids are unique


def test_every_case_has_a_trap_query():
    assert set(WRONG_SQL) == set(CASES)


@pytest.mark.parametrize("case", load_golden(), ids=lambda c: c["id"])
def test_case_is_well_formed(case):
    assert set(case) == REQUIRED_FIELDS
    assert case["category"] in CATEGORIES
    assert case["difficulty"] in DIFFICULTIES
    assert isinstance(case["order_matters"], bool)


def test_all_categories_covered():
    assert {c["category"] for c in CASES.values()} == CATEGORIES


@pytest.mark.parametrize("case", load_golden(), ids=lambda c: c["id"])
def test_gold_sql_runs_and_returns_rows(case, db_path):
    result = run_sql(case["gold_sql"], db_path)
    assert result.ok, result.error
    assert result.rows, "gold query returned no rows"


@pytest.mark.parametrize("case_id", sorted(WRONG_SQL))
def test_trap_query_fails(case_id, db_path):
    case = CASES[case_id]
    result = exec_match(WRONG_SQL[case_id], case["gold_sql"], db_path, case["order_matters"])
    assert not result.passed, f"trap in {case_id} does not bite"


@pytest.mark.parametrize("case_id", sorted(ALT_CORRECT_SQL))
def test_alternative_correct_query_passes(case_id, db_path):
    case = CASES[case_id]
    result = exec_match(ALT_CORRECT_SQL[case_id], case["gold_sql"], db_path, case["order_matters"])
    assert result.passed, result.reason


# Pin a few answers so a change to seed data can't silently move the traps.
def test_known_answers(db_path):
    def rows(case_id):
        return sorted(run_sql(CASES[case_id]["gold_sql"], db_path).rows)

    assert rows("q002") == [(15, "Nina Patel"), (19, "Zara Ahmed")]
    assert rows("q005") == [(26,)]
    assert rows("q006") == [(6, "Chen Wei"), (10, "Omar Haddad"), (15, "Nina Patel")]
    assert rows("q008") == [(1, 14500.5), (3, 1800.25)]
    assert rows("q009") == [(8,)]
    assert len(rows("q010")) == 20
    assert rows("q013") == [(10, "Omar Haddad")]
    assert rows("q014") == [("SOL",)]
    assert rows("q036") == [(1,), (3,)]
    assert rows("q046") == [(11,), (28,)]
    assert rows("q050") == [(7,), (8,)]
    assert [r for r in rows("q047") if r[0] == "USD"] == [("USD", 23), ("USD", 27)]
