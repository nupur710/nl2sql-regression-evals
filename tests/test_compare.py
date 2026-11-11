"""compare.py tests with synthetic run files (no API calls)."""

import json

from evals.compare import Side, compare, main, render_markdown

IDS = [f"q{i:03d}" for i in range(1, 51)]


def make_run(failing=(), ids=IDS, agent_errors=0, prompt="v1"):
    cases = [{"id": i, "category": "join" if int(i[1:]) % 2 else "date",
              "question": f"question {i}", "passed": i not in failing} for i in ids]
    return {"meta": {"prompt_version": prompt, "model": "claude-haiku-5-5", "effort": "medium"},
            "summary": {"agent_errors": agent_errors}, "cases": cases}


def sides(base_runs, head_runs):
    return Side(base_runs), Side(head_runs)


def test_identical_runs_pass():
    base, head = sides([make_run({"q040"})], [make_run({"q040"})])
    result = compare(base, head)
    assert result.status == "pass"
    assert result.delta == 0
    assert result.still_failing == ["q040"]


def test_drop_within_threshold_passes():
    # 1 more failure out of 50 = -2 points; threshold is 4.
    base, head = sides([make_run()], [make_run({"q001"})])
    result = compare(base, head, max_drop=0.04)
    assert result.status == "pass"
    assert result.regressions == [("q001", 1.0, 0.0)]


def test_drop_exactly_at_threshold_passes():
    base, head = sides([make_run()], [make_run({"q001", "q002"})])  # -4 points
    assert compare(base, head, max_drop=0.04).status == "pass"


def test_drop_beyond_threshold_is_regression():
    base, head = sides([make_run()], [make_run({"q001", "q002", "q003"})])  # -6 points
    result = compare(base, head, max_drop=0.04)
    assert result.status == "regression"
    assert round(result.delta, 4) == -0.06


def test_repeats_are_averaged():
    # A flaky case (passes 1 of 2 runs on head) counts as half a failure.
    base = [make_run(), make_run()]
    head = [make_run({"q001"}), make_run()]
    result = compare(*sides(base, head))
    assert round(result.head_rate, 4) == round(1 - 0.5 / 50, 4)
    assert result.regressions == [("q001", 1.0, 0.5)]


def test_improvements_are_listed():
    base, head = sides([make_run({"q005"})], [make_run()])
    result = compare(base, head)
    assert result.improvements == [("q005", 0.0, 1.0)]
    assert result.status == "pass"


def test_api_errors_make_status_error_even_if_scores_look_fine():
    base, head = sides([make_run()], [make_run(agent_errors=1)])
    assert compare(base, head).status == "error"


def test_no_baseline():
    base, head = sides([], [make_run({"q010"})])
    result = compare(base, head)
    assert result.status == "no_baseline"
    assert result.head_rate == 0.98


def test_only_shared_cases_are_compared_when_test_set_changes():
    base = [make_run(ids=IDS[:40])]
    head = [make_run(failing={"q045", "q046", "q047"})]  # new cases fail, shared all pass
    result = compare(*sides(base, head))
    assert len(result.shared_ids) == 40
    assert result.added == IDS[40:]
    assert result.status == "pass"


def test_markdown_mentions_key_facts():
    base, head = sides([make_run()], [make_run({"q001", "q002", "q003"}, prompt="v2")])
    md = render_markdown(compare(base, head), base, head)
    assert "Eval failed" in md
    assert "100.0% → 94.0%" in md
    assert "| q001 | join | 1/1 | 0/1 | question q001 |" in md
    assert "| Prompt | v1 | v2 |" in md


def test_cli_exit_codes_and_report(tmp_path):
    def write(name, run):
        path = tmp_path / name
        path.write_text(json.dumps(run))
        return str(path)

    good, bad = write("good.json", make_run()), write("bad.json", make_run({"q001", "q002", "q003"}))
    out = tmp_path / "report.md"
    assert main(["--base", good, "--head", good, "--out", str(out)]) == 0
    assert "Eval passed" in out.read_text(encoding="utf-8")
    assert main(["--base", good, "--head", bad]) == 1
    assert main(["--head", good]) == 0  # no baseline
