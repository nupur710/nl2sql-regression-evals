from evals.graders.executes import executes, run_sql

INFINITE_QUERY = (
    "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) "
    "SELECT COUNT(*) FROM c"
)


def test_valid_query_returns_rows(db_path):
    result = run_sql("SELECT COUNT(*) FROM users", db_path)
    assert result.ok
    assert result.rows == [(20,)]
    assert result.error is None


def test_valid_query_with_no_rows_still_executes(db_path):
    result = run_sql("SELECT * FROM users WHERE user_id = -1", db_path)
    assert result.ok
    assert result.rows == []


def test_syntax_error_fails(db_path):
    result = run_sql("SELEC * FROM users", db_path)
    assert not result.ok
    assert "syntax error" in result.error


def test_missing_table_fails(db_path):
    result = run_sql("SELECT * FROM customers", db_path)
    assert not result.ok
    assert "no such table" in result.error


def test_missing_column_fails(db_path):
    assert not executes("SELECT username FROM users", db_path)


def test_empty_sql_fails(db_path):
    assert not executes("", db_path)
    assert not executes("   \n", db_path)


def test_writes_are_blocked(db_path):
    result = run_sql("DELETE FROM users", db_path)
    assert not result.ok
    assert "readonly" in result.error
    # And the data is untouched.
    assert run_sql("SELECT COUNT(*) FROM users", db_path).rows == [(20,)]


def test_multiple_statements_fail(db_path):
    assert not executes("SELECT 1; SELECT 2", db_path)


def test_slow_query_times_out(db_path):
    result = run_sql(INFINITE_QUERY, db_path, timeout_s=0.2)
    assert not result.ok
    assert "timeout" in result.error


def test_connection_usable_after_timeout(db_path):
    run_sql(INFINITE_QUERY, db_path, timeout_s=0.2)
    assert executes("SELECT 1", db_path)
