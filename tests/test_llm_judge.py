"""LLM judge tests with a fake client (no API calls)."""

import json
from types import SimpleNamespace

import pytest

from evals.graders.llm_judge import LLMJudge, format_submission, load_judge_prompt, parse_verdict


class FakeClient:
    def __init__(self, text, stop_reason="end_turn"):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
        self._text, self._stop = text, stop_reason

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self._text)],
            stop_reason=self._stop, model=kwargs["model"],
            usage=SimpleNamespace(input_tokens=900, output_tokens=60),
        )


def verdict_json(correct, reasoning="ok"):
    return json.dumps({"reasoning": reasoning, "correct": correct})


@pytest.mark.parametrize("text, expected", [
    (verdict_json(True, "fine"), (True, "fine")),
    (verdict_json(False, "misses NULLs"), (False, "misses NULLs")),
])
def test_parse_valid_verdicts(text, expected):
    assert parse_verdict(text) == expected


@pytest.mark.parametrize("text", ["not json", '{"reasoning": "x"}', '{"correct": "yes"}', "[]"])
def test_parse_invalid_verdicts_give_none(text):
    correct, message = parse_verdict(text)
    assert correct is None
    assert message


def test_prompt_contains_schema_and_no_placeholder():
    prompt = load_judge_prompt("v1")
    assert "CREATE TABLE accounts" in prompt
    assert "{schema}" not in prompt


def test_submission_includes_question_and_sql():
    text = format_submission("How many users?", "SELECT COUNT(*) FROM users")
    assert "How many users?" in text and "SELECT COUNT(*) FROM users" in text


def test_judge_returns_verdict_and_sends_structured_output_request():
    client = FakeClient(verdict_json(False, "drops ties"))
    result = LLMJudge(client=client, model="claude-sonnet-5-5", effort="low").judge("Q?", "SELECT 1")
    assert result.correct is False
    assert result.reasoning == "drops ties"
    call = client.calls[0]
    assert call["output_config"]["effort"] == "low"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "gold" not in call["messages"][0]["content"].lower()  # judge never sees the answer


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_no_verdict_on_refusal_or_truncation(stop_reason):
    client = FakeClient(verdict_json(True), stop_reason=stop_reason)
    assert LLMJudge(client=client).judge("Q?", "SELECT 1").correct is None


def test_default_model_is_configurable(monkeypatch):
    monkeypatch.setenv("JUDGE_MODEL", "claude-haiku-5-5")
    judge = LLMJudge(client=FakeClient(verdict_json(True)))
    assert judge.model == "claude-haiku-5-5"
    judge.judge("Q?", "SELECT 1")
    assert "fallbacks" not in judge.client.calls[0]
