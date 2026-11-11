"""Eval runner tests, using fake agents (no API calls)."""

from agent.sql_agent import AgentResult
from evals.run_eval import evaluate, load_golden, summarize

CASES = load_golden()


def _result(sql):
    return AgentResult(sql=sql, raw_text=sql, stop_reason="end_turn", model="fake",
                       input_tokens=100, output_tokens=10, latency_s=0.0)


class OracleAgent:
    """Answers every question with the gold SQL: must score 100%."""
    def __init__(self, cases):
        self.answers = {c["question"]: c["gold_sql"] for c in cases}

    def generate_sql(self, question):
        return _result(self.answers[question])


class FixedAgent:
    def __init__(self, sql):
        self.sql = sql

    def generate_sql(self, question):
        return _result(self.sql)


class CrashingAgent:
    def generate_sql(self, question):
        raise ConnectionError("network down")


def test_oracle_agent_scores_100_percent(db_path):
    summary = summarize(evaluate(CASES, OracleAgent(CASES), db_path))
    assert summary["pass_rate"] == 1.0
    assert summary["executes_rate"] == 1.0
    assert summary["agent_errors"] == 0


def test_parallel_run_matches_sequential_and_keeps_order(db_path):
    sequential = evaluate(CASES, OracleAgent(CASES), db_path, workers=1)
    parallel = evaluate(CASES, OracleAgent(CASES), db_path, workers=8)
    assert parallel == sequential
    assert [r["id"] for r in parallel] == [c["id"] for c in CASES]


def test_broken_sql_scores_zero(db_path):
    records = evaluate(CASES, FixedAgent("SELEC nonsense"), db_path)
    summary = summarize(records)
    assert summary["pass_rate"] == 0.0
    assert summary["executes_rate"] == 0.0
    assert all(r["reason"].startswith("pred_error") for r in records)


def test_valid_but_wrong_sql_executes_but_fails(db_path):
    summary = summarize(evaluate(CASES, FixedAgent("SELECT 1"), db_path))
    assert summary["executes_rate"] == 1.0
    assert summary["pass_rate"] == 0.0


def test_agent_crash_is_recorded_not_raised(db_path):
    records = evaluate(CASES[:2], CrashingAgent(), db_path)
    assert [r["passed"] for r in records] == [False, False]
    assert records[0]["reason"] == "agent_error: ConnectionError: network down"
    assert summarize(records)["agent_errors"] == 2


def test_records_keep_case_info_and_prediction(db_path):
    record = evaluate(CASES[:1], FixedAgent("SELECT 1"), db_path)[0]
    assert record["id"] == CASES[0]["id"]
    assert record["category"] == CASES[0]["category"]
    assert record["pred_sql"] == "SELECT 1"
    assert record["input_tokens"] == 100


def test_summary_breakdowns():
    records = [
        {"category": "join", "difficulty": "easy", "passed": True, "executes": True, "reason": "match"},
        {"category": "join", "difficulty": "hard", "passed": False, "executes": True, "reason": "value_mismatch"},
        {"category": "date", "difficulty": "easy", "passed": False, "executes": False, "reason": "agent_error: x"},
    ]
    summary = summarize(records)
    assert summary["pass_rate"] == round(1 / 3, 4)
    assert summary["executes_rate"] == round(2 / 3, 4)
    assert summary["agent_errors"] == 1
    assert summary["by_category"]["join"] == {"n": 2, "passed": 1, "pass_rate": 0.5}
    assert summary["by_difficulty"]["easy"] == {"n": 2, "passed": 1, "pass_rate": 0.5}
    assert summary["input_tokens"] == 0  # missing token counts default to 0


def test_empty_run_summary():
    assert summarize([])["pass_rate"] == 0.0
