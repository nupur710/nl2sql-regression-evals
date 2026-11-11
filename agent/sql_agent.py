"""Natural-language question -> SQL string, using Claude.

Deliberately simple: one API call per question, no tools, no retries on bad SQL.
The repo is about evaluating this agent, not about making it clever.

Configuration (environment variables):
  ANTHROPIC_API_KEY   required (read by the Anthropic SDK)
  SQL_AGENT_MODEL     default: claude-haiku-5-5
  SQL_AGENT_EFFORT    default: medium   (low | medium | high | xhigh | max)
"""

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import anthropic

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "data" / "schema.sql"

DEFAULT_MODEL = "claude-haiku-5-5"  # cheap enough to run on every PR
DEFAULT_EFFORT = "medium"
MAX_TOKENS = 16000

# Server-side refusal fallback: if the model declines, the API retries on another
# model. We record which model actually answered (AgentResult.model) so a
# fallback can never silently change what we're measuring.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5",
                   "claude-fable-5-1", "claude-fable-5-2"}


@dataclass
class AgentResult:
    sql: str            # extracted SQL ("" if none found)
    raw_text: str       # the model's full text reply
    stop_reason: str
    model: str          # model that actually served the request
    input_tokens: int
    output_tokens: int
    latency_s: float


def load_prompt(version):
    """Read agent/prompts/<version>.txt and insert the schema."""
    template = (PROMPTS_DIR / f"{version}.txt").read_text(encoding="utf-8")
    schema = SCHEMA_PATH.read_text(encoding="utf-8").strip()
    return template.replace("{schema}", schema)


# A ``` fence, optionally followed by a language tag line (```sql, ```sqlite, ...).
_FENCE = re.compile(r"```(?:[A-Za-z]+\n)?\s*(.*?)```", re.DOTALL)


def extract_sql(text):
    """Pull the SQL out of a reply: the first fenced block, else the whole text."""
    match = _FENCE.search(text)
    sql = match.group(1) if match else text
    return sql.strip().rstrip(";").strip()


class SQLAgent:
    def __init__(self, prompt_version="v1", model=None, effort=None, client=None):
        self.prompt_version = prompt_version
        self.model = model or os.environ.get("SQL_AGENT_MODEL", DEFAULT_MODEL)
        self.effort = effort or os.environ.get("SQL_AGENT_EFFORT", DEFAULT_EFFORT)
        self.system_prompt = load_prompt(prompt_version)
        self.client = client or anthropic.Anthropic()

    def _request_options(self):
        options = {"output_config": {"effort": self.effort}}
        if self.model in FALLBACK_MODELS:
            options.update(betas=[FALLBACK_BETA], fallbacks="default")
        return options

    def generate_sql(self, question):
        """Ask the model for SQL. API errors propagate; bad answers don't raise."""
        start = time.monotonic()
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=self.system_prompt,
            messages=[{"role": "user", "content": question}],
            **self._request_options(),
        )
        latency = time.monotonic() - start

        text = "".join(block.text for block in response.content if block.type == "text")
        return AgentResult(
            sql=extract_sql(text),
            raw_text=text,
            stop_reason=response.stop_reason,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_s=round(latency, 3),
        )
