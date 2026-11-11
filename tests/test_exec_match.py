import pytest

from evals.graders.exec_match import exec_match, normalize_value, results_match


# --- normalize_value -------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (5, 5.0),
    (5.0, 5.0),
    (1.23456789, 1.2346),
    (None, None),
    ("Alex Kim", "Alex Kim"),
])
def test_normalize_value(value, expected):
    assert normalize_value(value) == expected


# --- results_match: pure comparison ----------------------------------------

def test_identical_rows_match():
    assert results_match([(1, "a"), (2, "b")], [(1, "a"), (2, "b")])


def test_row_order_ignored_by_default():
    assert results_match([(2, "b"), (1, "a")], [(1, "a"), (2, "b")])


def test_row_order_enforced_when_order_matters():
    assert not results_match([(2, "b"), (1, "a")], [(1, "a"), (2, "b")], order_matters=True)
    assert results_match([(1, "a"), (2, "b")], [(1, "a"), (2, "b")], order_matters=True)


def test_floats_equal_after_rounding_to_4dp():
    assert results_match([(56.599999999999994,)], [(56.6,)])
    assert results_match([(0.12341,)], [(0.12344,)])  # both -> 0.1234


def test_floats_differing_at_4dp_do_not_match():
    assert not results_match([(1.0001,)], [(1.0002,)])


def test_int_and_float_match():
    assert results_match([(0,)], [(0.0,)])
    assert results_match([(26,)], [(26.0,)])


def test_null_matches_null():
    assert results_match([(1, None)], [(1, None)])


def test_null_does_not_match_zero():
    assert not results_match([(1, None)], [(1, 0)])


def test_number_does_not_match_string():
    assert not results_match([("5",)], [(5,)])


def test_duplicate_rows_are_counted():
    assert not results_match([(1,), (1,), (2,)], [(1,), (2,)])
    assert not results_match([(1,), (2,)], [(1,), (1,), (2,)])


def test_extra_row_fails():
    assert not results_match([(1,), (2,), (3,)], [(1,), (2,)])


def test_missing_row_fails():
    assert not results_match([(1,)], [(1,), (2,)])


def test_both_empty_match():
    assert results_match([], [])


def test_empty_vs_nonempty_fails():
    assert not results_match([], [(1,)])


def test_extra_column_fails():
    assert not results_match([(1, "a", "x")], [(1, "a")])


def test_column_order_matters():
    assert not results_match([("a", 1)], [(1, "a")])


# --- exec_match: runs SQL against the db -----------------------------------

GOLD = "SELECT user_id, full_name FROM users WHERE country IS NULL"


def test_exec_match_ignores_aliases_and_order(db_path):
    pred = ("SELECT user_id AS id, full_name AS name FROM users "
            "WHERE country IS NULL ORDER BY user_id DESC")
    assert exec_match(pred, GOLD, db_path).passed


def test_exec_match_reports_pred_error(db_path):
    result = exec_match("SELECT nope FROM users", GOLD, db_path)
    assert not result.passed
    assert result.reason.startswith("pred_error")


def test_exec_match_reports_gold_error(db_path):
    result = exec_match(GOLD, "SELECT nope FROM users", db_path)
    assert not result.passed
    assert result.reason.startswith("gold_error")


def test_exec_match_reports_row_count_mismatch(db_path):
    result = exec_match("SELECT user_id, full_name FROM users", GOLD, db_path)
    assert result.reason == "row_count_mismatch"


def test_exec_match_reports_value_mismatch(db_path):
    pred = "SELECT user_id, email FROM users WHERE country IS NULL"
    result = exec_match(pred, GOLD, db_path)
    assert result.reason == "value_mismatch"


def test_exec_match_timeout_is_a_fail(db_path):
    slow = ("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) "
            "SELECT COUNT(*) FROM c")
    result = exec_match(slow, GOLD, db_path, timeout_s=0.2)
    assert not result.passed
    assert "timeout" in result.reason
