"""Agent tests. No real API calls: a fake client stands in for Anthropic."""

from types import SimpleNamespace

import pytest

from agent.sql_agent import SQLAgent, extract_sql, load_prompt


@pytest.mark.parametrize("reply, expected", [
    ("```sql\nSELECT 1\n```", "SELECT 1"),
    ("```SQL\nSELECT 1\n```", "SELECT 1"),
    ("```sqlite\nSELECT 1\n```", "SELECT 1"),
    ("```\nSELECT 1\n```", "SELECT 1"),
    ("```SELECT 1```", "SELECT 1"),
    ("Here you go:\n```sql\nSELECT 1;\n```\nHope that helps!", "SELECT 1"),
    ("SELECT 1;", "SELECT 1"),
    ("  SELECT\n  1  ", "SELECT\n  1"),
    ("```sql\nSELECT 1\n```\n```sql\nSELECT 2\n```", "SELECT 1"),  # first block wins
    ("", ""),
])
def test_extract_sql(reply, expected):
    assert extract_sql(reply) == expected


def test_prompt_contains_schema():
    prompt = load_prompt("v1")
    assert "CREATE TABLE transactions" in prompt
    assert "{schema}" not in prompt


def test_unknown_prompt_version_fails():
    with pytest.raises(FileNotFoundError):
        load_prompt("does_not_exist")


class FakeClient:
    """Mimics client.beta.messages.create and records what it was called with."""

    def __init__(self, reply_text, served_model="claude-opus-5-5"):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
        self._reply = reply_text
        self._served_model = served_model

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="thinking", thinking=""),
                     SimpleNamespace(type="text", text=self._reply)],
            stop_reason="end_turn",
            model=self._served_model,
            usage=SimpleNamespace(input_tokens=1200, output_tokens=80),
        )


def test_generate_sql_extracts_sql_and_usage():
    client = FakeClient("```sql\nSELECT COUNT(*) FROM users\n```")
    result = SQLAgent(client=client, model="claude-opus-5-5", effort="medium") \
        .generate_sql("How many users?")
    assert result.sql == "SELECT COUNT(*) FROM users"
    assert result.stop_reason == "end_turn"
    assert result.input_tokens == 1200
    assert result.output_tokens == 80


def test_generate_sql_sends_expected_request():
    client = FakeClient("SELECT 1")
    SQLAgent(client=client, model="claude-opus-5-5", effort="low").generate_sql("Q?")
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"] == {"effort": "low"}
    assert call["messages"] == [{"role": "user", "content": "Q?"}]
    assert "users(" in call["system"]  # compact schema in prompt v2
    assert call["fallbacks"] == "default"


def test_no_fallback_for_models_without_it():
    client = FakeClient("SELECT 1")
    SQLAgent(client=client, model="claude-haiku-5-5").generate_sql("Q?")
    assert "fallbacks" not in client.calls[0]


def test_records_model_that_actually_served():
    client = FakeClient("SELECT 1", served_model="claude-opus-4-8")
    result = SQLAgent(client=client, model="claude-opus-5-5").generate_sql("Q?")
    assert result.model == "claude-opus-4-8"


def test_env_vars_configure_model_and_effort(monkeypatch):
    monkeypatch.setenv("SQL_AGENT_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("SQL_AGENT_EFFORT", "high")
    agent = SQLAgent(client=FakeClient("SELECT 1"))
    assert agent.model == "claude-sonnet-5-5"
    assert agent.effort == "high"
