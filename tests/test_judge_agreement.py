"""Judge agreement tests with fake judges (no API calls)."""

import pytest

from evals.graders.llm_judge import JudgeResult
from evals.judge_agreement import (cohens_kappa, confusion, judge_items, label_items,
                                   render_markdown, summarize, trap_items)
from evals.run_eval import load_golden

CASES = load_golden()


def _verdict(correct):
    return JudgeResult(correct=correct, reasoning="r", model="fake", stop_reason="end_turn",
                       input_tokens=10, output_tokens=2)


class AlwaysYesJudge:
    def judge(self, question, sql):
        return _verdict(True)


class PerfectJudge:
    """Cheats by knowing each question's gold SQL, to test the plumbing.
    (Must match per question: some trap queries are another case's gold SQL.)"""
    def __init__(self, cases):
        self.gold = {c["question"]: c["gold_sql"] for c in cases}

    def judge(self, question, sql):
        return _verdict(sql == self.gold[question])


class BrokenJudge:
    def judge(self, question, sql):
        raise TimeoutError("slow")


# --- Cohen's kappa ---------------------------------------------------------------

def test_kappa_textbook_example():
    # Classic example: po = 0.7, pe = 0.5 -> kappa = 0.4
    assert cohens_kappa(tp=20, fp=5, fn=10, tn=15) == pytest.approx(0.4)


def test_kappa_perfect_agreement():
    assert cohens_kappa(tp=30, fp=0, fn=0, tn=20) == pytest.approx(1.0)


def test_kappa_chance_level_is_zero():
    assert cohens_kappa(tp=25, fp=25, fn=25, tn=25) == pytest.approx(0.0)


def test_kappa_rubber_stamp_judge_is_zero_despite_high_accuracy():
    # Judge says "correct" to everything; 90% of items are correct -> 90% accuracy, kappa 0.
    assert cohens_kappa(tp=90, fp=10, fn=0, tn=0) == pytest.approx(0.0)


def test_kappa_undefined_cases():
    assert cohens_kappa(0, 0, 0, 0) is None
    assert cohens_kappa(tp=50, fp=0, fn=0, tn=0) is None  # everyone always says yes


# --- items and labels --------------------------------------------------------------

def test_trap_items_are_balanced_and_labelled_by_execution(db_path):
    items = label_items(trap_items(CASES), CASES, db_path)
    assert len(items) == 100
    assert all(it["exec_pass"] for it in items if it["source"] == "gold")
    assert not any(it["exec_pass"] for it in items if it["source"] == "trap")


def test_confusion_counts():
    items = [
        {"exec_pass": True, "judge_correct": True},
        {"exec_pass": False, "judge_correct": True},   # fooled
        {"exec_pass": True, "judge_correct": False},   # too strict
        {"exec_pass": False, "judge_correct": False},
        {"exec_pass": False, "judge_correct": None},   # no verdict: not counted
    ]
    assert confusion(items) == {"tp": 1, "fp": 1, "fn": 1, "tn": 1}


def test_perfect_judge_scores_kappa_one(db_path):
    items = label_items(trap_items(CASES), CASES, db_path)
    summary = summarize(judge_items(items, PerfectJudge(CASES), workers=4))
    assert summary["accuracy"] == 1.0
    assert summary["kappa"] == pytest.approx(1.0)
    assert summary["false_pass_rate"] == 0.0


def test_rubber_stamp_judge_is_fooled_by_every_trap(db_path):
    items = label_items(trap_items(CASES), CASES, db_path)
    summary = summarize(judge_items(items, AlwaysYesJudge()))
    assert summary["accuracy"] == 0.5
    assert summary["false_pass_rate"] == 1.0
    assert summary["kappa"] == pytest.approx(0.0)


def test_judge_errors_become_no_verdict(db_path):
    items = label_items(trap_items(CASES[:3]), CASES, db_path)
    judged = judge_items(items, BrokenJudge())
    assert all(it["judge_correct"] is None for it in judged)
    assert summarize(judged)["no_verdict"] == 6


def test_report_lists_fooled_items(db_path):
    items = judge_items(label_items(trap_items(CASES[:2]), CASES, db_path), AlwaysYesJudge())
    meta = {"judge_model": "fake", "judge_effort": "low", "judge_prompt": "v1",
            "sources": "test", "run_at": "now"}
    md = render_markdown(summarize(items), items, meta)
    assert "q001:trap" in md and "q002:trap" in md
    assert "Cohen's kappa" in md
