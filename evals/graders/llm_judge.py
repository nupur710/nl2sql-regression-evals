"""Grader 3 (secondary): an LLM judges whether a SQL query answers the question.

The judge sees what a human reviewer would: the schema, the question and the SQL.
It does NOT see the gold query or the data. Execution grading stays the source of
truth; judge_agreement.py measures how often this judge agrees with it.

Configuration (environment variables):
  JUDGE_MODEL    default: claude-sonnet-5-5  (a different model from the agent, to
                 avoid a model grading its own style of answer)
  JUDGE_EFFORT   default: medium
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

import anthropic

from agent.sql_agent import FALLBACK_BETA, FALLBACK_MODELS, SCHEMA_PATH

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_EFFORT = "medium"
MAX_TOKENS = 16000

# Structured output: the API guarantees the reply is JSON matching this schema.
# "reasoning" comes first so the model explains before it commits to a verdict.
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "correct": {"type": "boolean"},
    },
    "required": ["reasoning", "correct"],
    "additionalProperties": False,
}


@dataclass
class JudgeResult:
    correct: bool | None    # None = no usable verdict (refusal, truncation, bad JSON)
    reasoning: str
    model: str
    stop_reason: str
    input_tokens: int
    output_tokens: int


def load_judge_prompt(version):
    template = (PROMPTS_DIR / f"judge_{version}.txt").read_text(encoding="utf-8")
    return template.replace("{schema}", SCHEMA_PATH.read_text(encoding="utf-8").strip())


def format_submission(question, sql):
    return f"Question: {question}\n\nSQL:\n```sql\n{sql}\n```"


def parse_verdict(text):
    """Return (correct, reasoning); (None, message) if the reply isn't a valid verdict."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None, f"unparseable judge reply: {text[:200]!r}"
    if not isinstance(data, dict) or not isinstance(data.get("correct"), bool):
        return None, f"judge reply missing boolean 'correct': {text[:200]!r}"
    return data["correct"], str(data.get("reasoning", ""))


class LLMJudge:
    def __init__(self, prompt_version="v1", model=None, effort=None, client=None):
        self.prompt_version = prompt_version
        self.model = model or os.environ.get("JUDGE_MODEL", DEFAULT_MODEL)
        self.effort = effort or os.environ.get("JUDGE_EFFORT", DEFAULT_EFFORT)
        self.system_prompt = load_judge_prompt(prompt_version)
        self.client = client or anthropic.Anthropic()

    def _request_options(self):
        options = {"output_config": {"effort": self.effort,
                                     "format": {"type": "json_schema", "schema": VERDICT_SCHEMA}}}
        if self.model in FALLBACK_MODELS:
            options.update(betas=[FALLBACK_BETA], fallbacks="default")
        return options

    def judge(self, question, sql):
        """Ask the judge for a verdict. API errors propagate; bad replies give correct=None."""
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=self.system_prompt,
            messages=[{"role": "user", "content": format_submission(question, sql)}],
            **self._request_options(),
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        if response.stop_reason in ("refusal", "max_tokens"):
            correct, reasoning = None, f"no verdict (stop_reason={response.stop_reason})"
        else:
            correct, reasoning = parse_verdict(text)
        return JudgeResult(
            correct=correct,
            reasoning=reasoning,
            model=response.model,
            stop_reason=response.stop_reason,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
