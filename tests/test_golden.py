"""Checks on the golden test cases themselves.

A bad golden case silently corrupts every eval run, so we verify that:
  1. every case is well-formed,
  2. every gold query runs and returns rows,
  3. each trap really bites: a known-wrong query FAILS the case,
  4. a differently-written correct query PASSES the case.
"""

import json
from pathlib import Path

import pytest

from evals.graders.exec_match import exec_match
from evals.graders.executes import run_sql

GOLDEN_PATH = Path(__file__).resolve().parent.parent / "data" / "golden.jsonl"
REQUIRED_FIELDS = {"id", "question", "gold_sql", "category", "difficulty", "order_matters", "notes"}
CATEGORIES = {"join", "aggregation", "null_handling", "ambiguity", "date", "trap"}
DIFFICULTIES = {"easy", "medium", "hard"}


def load_golden():
    with GOLDEN_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


CASES = {case["id"]: case for case in load_golden()}

# A plausible mistake for each case. Each must NOT match gold.
WRONG_SQL = {
    "q001": "SELECT u.user_id, COUNT(*) FROM users u LEFT JOIN accounts a ON a.user_id = u.user_id GROUP BY u.user_id",
    "q002": "SELECT u.user_id, u.full_name FROM users u JOIN accounts a ON a.user_id = u.user_id WHERE a.account_id IS NULL",
    "q003": "SELECT a.currency, SUM(t.amount) FROM transactions t JOIN accounts a ON a.account_id = t.account_id WHERE t.txn_type = 'deposit' GROUP BY a.currency",
    "q004": "SELECT s.asset_class, AVG(t.quantity * s.price) FROM transactions t JOIN assets s ON s.asset_id = t.asset_id WHERE t.txn_type = 'buy' AND t.status = 'completed' GROUP BY s.asset_class HAVING AVG(t.quantity * s.price) > 2000",
    "q005": "SELECT COUNT(*) FROM accounts WHERE balance > 0",
    "q006": "SELECT user_id, full_name FROM users WHERE country = NULL",
    "q007": "SELECT SUM(t.quantity * s.price) FROM transactions t JOIN assets s ON s.asset_id = t.asset_id WHERE s.symbol = 'AAPL' AND t.txn_type = 'buy' AND t.status = 'completed'",
    "q008": "SELECT u.full_name, SUM(a.balance) FROM users u JOIN accounts a ON a.user_id = u.user_id WHERE u.full_name = 'Alex Kim' GROUP BY u.full_name",
    "q009": "SELECT COUNT(*) FROM transactions WHERE created_at BETWEEN '2026-03-01' AND '2026-03-31'",
    "q010": "SELECT u.user_id, SUM(t.amount) FROM users u LEFT JOIN accounts a ON a.user_id = u.user_id LEFT JOIN transactions t ON t.account_id = a.account_id WHERE t.txn_type = 'fee' GROUP BY u.user_id",
    "q011": "SELECT a.user_id, SUM(a.balance), COUNT(t.txn_id) FROM accounts a JOIN transactions t ON t.account_id = a.account_id WHERE a.currency = 'USD' GROUP BY a.user_id",
    "q012": "SELECT u.user_id, u.full_name FROM users u WHERE u.referred_by IS NOT NULL",
    "q013": "SELECT DISTINCT u.user_id, u.full_name FROM users u JOIN accounts a ON a.user_id = u.user_id WHERE a.closed_at IS NOT NULL",
    "q014": "SELECT symbol FROM assets WHERE asset_id NOT IN (SELECT asset_id FROM transactions)",
    "q015": "SELECT u.country, COUNT(*) FROM users u JOIN accounts a ON a.user_id = u.user_id JOIN transactions t ON t.account_id = a.account_id WHERE t.txn_type = 'buy' AND t.status = 'completed' AND u.country IS NOT NULL GROUP BY u.country",
    "q016": "SELECT DISTINCT u.user_id, u.full_name FROM users u JOIN accounts a ON a.user_id = u.user_id WHERE a.account_type = 'checking' OR a.account_type = 'brokerage'",
    "q017": "SELECT 100 * SUM(status = 'failed') / COUNT(*) FROM transactions",
    "q018": "SELECT a.currency, SUM(t.amount) FROM transactions t JOIN accounts a ON a.account_id = t.account_id WHERE t.status = 'completed' AND t.txn_type IN ('deposit', 'withdrawal') GROUP BY a.currency",
    "q019": "SELECT AVG(n) FROM (SELECT user_id, COUNT(*) AS n FROM accounts GROUP BY user_id)",
    "q020": "SELECT a.user_id, SUM(t.amount) AS total FROM transactions t JOIN accounts a ON a.account_id = t.account_id WHERE a.currency = 'USD' AND t.txn_type = 'buy' GROUP BY a.user_id ORDER BY total DESC LIMIT 3",
    "q021": "SELECT account_id, COUNT(*) FROM transactions GROUP BY account_id HAVING COUNT(*) >= 11",
    "q022": "SELECT txn_type, COUNT(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), COUNT(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) FROM transactions GROUP BY txn_type",
    "q023": "SELECT COUNT(*) FROM transactions WHERE txn_type = 'deposit'",
    "q024": "SELECT user_id FROM users WHERE user_id NOT IN (SELECT referred_by FROM users)",
    "q025": "SELECT COUNT(asset_id) FROM transactions WHERE asset_id IS NULL",
    "q026": "SELECT user_id, country FROM users",
    "q027": "SELECT COUNT(*) FROM users WHERE referred_by != 1",
    "q028": "SELECT COUNT(country), COUNT(country IS NULL) FROM users",
    "q029": "SELECT user_id, MAX(closed_at) FROM accounts WHERE closed_at IS NOT NULL GROUP BY user_id",
    "q030": "SELECT user_id FROM users ORDER BY country, user_id",
    "q031": "SELECT DISTINCT a.user_id FROM transactions t JOIN accounts a ON a.account_id = t.account_id JOIN assets s ON s.asset_id = t.asset_id WHERE s.name = 'Apple' AND t.txn_type = 'buy' AND t.status = 'completed'",
    "q032": "SELECT balance FROM accounts WHERE account_id = 9",
    "q033": "SELECT SUM(balance) FROM accounts WHERE closed_at IS NULL",
    "q034": "SELECT SUM(t.amount) FROM transactions t JOIN assets s ON s.asset_id = t.asset_id WHERE s.symbol = 'AAPL' AND t.txn_type = 'buy' AND t.status = 'completed'",
    "q035": "SELECT COUNT(*) FROM users",
    "q036": "SELECT MIN(user_id) FROM users GROUP BY full_name HAVING COUNT(*) > 1",
    "q037": "SELECT SUM(t.amount) FROM transactions t JOIN assets s ON s.asset_id = t.asset_id WHERE s.symbol = 'AAPL' AND t.txn_type = 'buy' AND t.status = 'completed'",
    "q038": "SELECT COUNT(*) FROM transactions WHERE created_at >= '2026-03-01' AND created_at < '2026-04-01'",
    "q039": "SELECT COUNT(*) FROM transactions WHERE created_at >= date('2026-06-30', '-7 days')",
    "q040": "SELECT strftime('%Y-%m', created_at), COUNT(*) FROM transactions WHERE created_at LIKE '2024%' GROUP BY 1",
    "q041": "SELECT AVG(julianday(settled_at) - julianday(created_at)) FROM transactions WHERE status = 'completed'",
    "q042": "SELECT account_id FROM accounts WHERE CAST(strftime('%Y', closed_at) AS INTEGER) - CAST(strftime('%Y', opened_at) AS INTEGER) <= 1",
    "q043": "SELECT COUNT(*) FROM transactions WHERE status = 'completed' AND strftime('%w', created_at) IN ('6', '7')",
    "q044": "SELECT u.user_id, julianday(MAX(a.opened_at)) - julianday(u.signup_date) FROM users u JOIN accounts a ON a.user_id = u.user_id GROUP BY u.user_id",
    "q045": "SELECT SUM(amount) FROM transactions WHERE txn_type = 'deposit' AND status = 'completed' AND created_at BETWEEN '2026-01-01' AND '2026-03-31'",
    "q046": "SELECT account_id FROM accounts WHERE currency = 'USD' ORDER BY balance DESC LIMIT 1",
    "q047": "SELECT currency, account_id FROM (SELECT a.currency, t.account_id, MAX(t.amount) FROM transactions t JOIN accounts a ON a.account_id = t.account_id WHERE t.txn_type = 'deposit' AND t.status = 'completed' GROUP BY a.currency)",
    "q048": "SELECT u.user_id, COUNT(*) FROM users u LEFT JOIN accounts a ON a.user_id = u.user_id LEFT JOIN transactions t ON t.account_id = a.account_id AND t.status = 'completed' AND t.created_at >= '2026-01-01' GROUP BY u.user_id",
    "q049": "SELECT s.symbol, SUM(t.quantity) FROM transactions t JOIN assets s ON s.asset_id = t.asset_id WHERE t.status = 'completed' AND t.txn_type IN ('buy', 'sell') GROUP BY s.symbol",
    "q050": "SELECT user_id FROM (SELECT a.user_id, COUNT(*) AS n FROM transactions t JOIN accounts a ON a.account_id = t.account_id WHERE t.status = 'completed' GROUP BY a.user_id) ORDER BY n DESC LIMIT 1 OFFSET 1",
}

# A correct query written differently from gold. Each MUST match gold.
ALT_CORRECT_SQL = {
    "q001": "SELECT user_id, COUNT(*) AS n FROM accounts GROUP BY user_id",
    "q002": "SELECT user_id, full_name FROM users WHERE user_id NOT IN (SELECT user_id FROM accounts)",
    "q005": "SELECT SUM(closed_at IS NULL) FROM accounts",
    "q007": "SELECT SUM(t.quantity * t.price) FROM transactions t WHERE t.txn_type = 'buy' AND t.status = 'completed' AND t.asset_id = (SELECT asset_id FROM assets WHERE symbol = 'AAPL')",
    "q009": "SELECT COUNT(*) FROM transactions WHERE strftime('%Y-%m', created_at) = '2026-03'",
    "q010": "SELECT u.user_id, (SELECT COALESCE(SUM(t.amount), 0) FROM transactions t JOIN accounts a ON a.account_id = t.account_id WHERE a.user_id = u.user_id AND t.txn_type = 'fee') FROM users u",
    "q011": "WITH tx AS (SELECT account_id, COUNT(*) AS n FROM transactions GROUP BY account_id) SELECT a.user_id, SUM(a.balance), SUM(COALESCE(tx.n, 0)) FROM accounts a LEFT JOIN tx ON tx.account_id = a.account_id WHERE a.currency = 'USD' GROUP BY a.user_id",
    "q013": "SELECT user_id, full_name FROM users WHERE user_id IN (SELECT user_id FROM accounts) AND user_id NOT IN (SELECT user_id FROM accounts WHERE closed_at IS NULL)",
    "q014": "SELECT s.symbol FROM assets s LEFT JOIN transactions t ON t.asset_id = s.asset_id WHERE t.txn_id IS NULL",
    "q016": "SELECT u.user_id, u.full_name FROM users u JOIN accounts a ON a.user_id = u.user_id WHERE a.account_type = 'checking' INTERSECT SELECT u.user_id, u.full_name FROM users u JOIN accounts a ON a.user_id = u.user_id WHERE a.account_type = 'brokerage'",
    "q017": "SELECT CAST(COUNT(CASE WHEN status = 'failed' THEN 1 END) AS REAL) * 100 / COUNT(*) FROM transactions",
    "q019": "SELECT AVG(n) FROM (SELECT u.user_id, COUNT(a.account_id) AS n FROM users u LEFT JOIN accounts a ON a.user_id = u.user_id GROUP BY u.user_id)",
    "q022": "SELECT txn_type, COUNT(CASE WHEN status = 'completed' THEN 1 END), COUNT(CASE WHEN status = 'failed' THEN 1 END) FROM transactions GROUP BY txn_type",
    "q024": "SELECT user_id FROM users WHERE user_id NOT IN (SELECT referred_by FROM users WHERE referred_by IS NOT NULL)",
    "q025": "SELECT COUNT(*) - COUNT(asset_id) FROM transactions",
    "q026": "SELECT user_id, CASE WHEN country IS NULL THEN 'Unknown' ELSE country END FROM users",
    "q027": "SELECT COUNT(*) FROM users WHERE referred_by IS NULL OR referred_by <> 1",
    "q028": "SELECT SUM(country IS NOT NULL), SUM(country IS NULL) FROM users",
    "q030": "SELECT user_id FROM users ORDER BY country NULLS LAST, user_id",
    "q031": "SELECT DISTINCT a.user_id FROM accounts a JOIN transactions t ON t.account_id = a.account_id WHERE t.txn_type = 'buy' AND t.status = 'completed' AND t.asset_id IN (SELECT asset_id FROM assets WHERE name LIKE 'Apple%')",
    "q036": "SELECT DISTINCT u1.user_id FROM users u1 JOIN users u2 ON u1.full_name = u2.full_name AND u1.user_id <> u2.user_id",
    "q039": "SELECT COUNT(*) FROM transactions WHERE date(created_at) BETWEEN date('2026-06-30', '-6 days') AND '2026-06-30'",
    "q040": "WITH m(month) AS (VALUES ('2024-01'), ('2024-02'), ('2024-03'), ('2024-04'), ('2024-05'), ('2024-06'), ('2024-07'), ('2024-08'), ('2024-09'), ('2024-10'), ('2024-11'), ('2024-12')) SELECT m.month, COUNT(t.txn_id) FROM m LEFT JOIN transactions t ON strftime('%Y-%m', t.created_at) = m.month GROUP BY m.month",
    "q041": "SELECT AVG((strftime('%s', settled_at) - strftime('%s', created_at)) / 3600.0) FROM transactions WHERE status = 'completed'",
    "q042": "SELECT account_id FROM accounts WHERE julianday(closed_at) - julianday(opened_at) < 365",
    "q044": "SELECT a.user_id, CAST(julianday(MIN(a.opened_at)) - julianday(u.signup_date) AS INTEGER) FROM accounts a JOIN users u ON u.user_id = a.user_id GROUP BY a.user_id",
    "q045": "SELECT SUM(amount) FROM transactions WHERE txn_type = 'deposit' AND status = 'completed' AND strftime('%Y-%m', created_at) IN ('2026-01', '2026-02', '2026-03')",
    "q046": "SELECT account_id FROM (SELECT account_id, RANK() OVER (ORDER BY balance DESC) AS r FROM accounts WHERE currency = 'USD') WHERE r = 1",
    "q047": "SELECT currency, account_id FROM (SELECT a.currency, t.account_id, RANK() OVER (PARTITION BY a.currency ORDER BY t.amount DESC) AS r FROM transactions t JOIN accounts a ON a.account_id = t.account_id WHERE t.txn_type = 'deposit' AND t.status = 'completed') WHERE r = 1",
    "q048": "SELECT u.user_id, (SELECT COUNT(*) FROM transactions t JOIN accounts a ON a.account_id = t.account_id WHERE a.user_id = u.user_id AND t.status = 'completed' AND t.created_at >= '2026-01-01') FROM users u",
    "q049": "SELECT s.symbol, SUM(CASE t.txn_type WHEN 'buy' THEN t.quantity WHEN 'sell' THEN -t.quantity END) FROM assets s JOIN transactions t ON t.asset_id = s.asset_id WHERE t.status = 'completed' GROUP BY s.symbol",
    "q050": "SELECT user_id FROM (SELECT a.user_id, DENSE_RANK() OVER (ORDER BY COUNT(*) DESC) AS r FROM transactions t JOIN accounts a ON a.account_id = t.account_id WHERE t.status = 'completed' GROUP BY a.user_id) WHERE r = 2",
}


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
