# SQL Agent Eval Pipeline

A natural-language → SQL agent with an automated eval suite. The focus is
the **evals**: execution-based grading is the source of truth, and the test cases
are designed to catch specific, realistic mistakes.

## Setup
```bash
python -m venv .venv
.venv\Scripts\activate   
pip install -r requirements.txt
```

## Configure
The agent calls Claude via the Anthropic API. Settings come from environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) |
| `SQL_AGENT_MODEL` | `claude-haiku-5-5` | Model to evaluate (e.g. `claude-opus-5-5`, `claude-sonnet-5-5`) |
| `SQL_AGENT_EFFORT` | `medium` | Reasoning effort: `low`, `medium`, `high`, `xhigh`, `max` |

## Run
```bash
python -m data.seed                   # build data/fintech.db (deterministic and safe to re-run)
python -m pytest                      # all tests; no API calls, no key needed for this
python -m evals.run_eval --limit 2    # cheap smoke test against the real API
python -m evals.run_eval              # full eval, prompt v1
python -m evals.run_eval --prompt v2  # evaluate another prompt version
```
Each eval run writes `results/<timestamp>_<prompt>.json` with run metadata, a summary
(pass rate, executes rate, per-category/difficulty breakdown, tokens), and one record per
case (the generated SQL, pass/fail and the reason).

## Comparing runs
```bash
python -m evals.compare --base results/a.json --head results/b.json --out report.md
```
Each side accepts several run files (repeats), which are averaged per case. Exit code 0 =
pass, 1 = pass rate dropped more than `--max-drop` (default 0.04 = 4 points), 2 = some API
calls failed, so the scores can't be trusted.

## CI regression gate
`.github/workflows/eval.yml` runs on every pull request:
1. Runs the unit tests.
2. Runs the eval 3 times on the target branch (base) and 3 times on the PR (head),
   in the same job, so both sides see the same model and API conditions.
3. Compares them with `compare.py` on the cases both sides share.
4. Posts the markdown report as a PR comment (updated on each push) and in the job summary.
5. Fails if the average pass rate dropped by more than 4 points, or if any API call failed.

**Why these numbers:** identical runs differ by about one case (2 points). Averaging 3
repeats per side shrinks that noise; a 4-point threshold (2 of 50 cases) is then
well above it, so the gate shouldn't block a PR by chance. Cost is about $0.06 per PR on Haiku.

**Setup (once):**
1. Add the repository secret `ANTHROPIC_API_KEY` (Settings → Secrets and variables → Actions).
2. To actually *block* merges, add a branch rule on `main` that requires the `eval` check
   to pass (Settings → Rules → Rulesets, or Branches → Branch protection).

PRs from forks don't receive secrets, so the eval can't run on them; the job fails with a
clear message. Don't switch to `pull_request_target` to work around this: it would run
untrusted PR code with your API key.

## The agent
`agent/sql_agent.py` makes one API call per question. The system prompt is
`agent/prompts/<version>.txt` with the schema inserted. The SQL is pulled out of the
reply's ```sql block. Prompts are versioned files so a prompt change is a reviewable diff.

Notes:
- Results can vary between runs: current Claude models don't accept `temperature`, so
  sampling can't be fixed.
- If the model refuses, the API can retry on a fallback model (`fallbacks="default"`).
  Every case records the model that actually answered, so this can't skew results unnoticed.
- `agent_errors` in the summary counts infrastructure failures (network, auth, rate
  limits), kept apart from wrong answers.

## The database
A small fintech schema (`data/schema.sql`): `users`, `accounts`, `assets`, `transactions`.
Rows are hand-written where a trap depends on them; bulk transactions come from a
fixed-seed generator, so every build has identical contents.

Deliberate traps:
| Trap | Where |
|---|---|
| Duplicate names | Users 1 and 3 are both "Alex Kim" |
| NULL meaning "still open" | `accounts.closed_at IS NULL` = open account |
| NULL country | Users 6, 10, 15 |
| Users with no accounts | Users 15, 19 (need a LEFT JOIN) |
| NULL foreign key | `transactions.asset_id` is NULL for cash transactions |
| Ambiguous column | `price` is in both `assets` (today's price) and `transactions` (price paid) |
| Month boundaries | Transactions at `2026-03-31 23:59:59` and `2026-04-01 00:00:00` |
| Empty months | No transactions in January or March 2024 |
| Status filters | Pending/failed transactions mixed in with completed ones |
| Ties | USD accounts 11 and 28 tie for top balance; two USD deposits tie at 3000.00 |
| Never traded | Asset SOL has no transactions |
| All accounts closed | User 10's only account is closed |

The schema comments state neutral facts only (formats, units, value ranges). An earlier
version also described what NULL meant and which `price` was which; that gave the traps
away, and Haiku scored 100%.

## Golden cases
`data/golden.jsonl`, one JSON object per line:
```json
{"id": "q001", "question": "...", "gold_sql": "...", "category": "join|aggregation|null_handling|ambiguity|date|trap", "difficulty": "easy|medium|hard", "order_matters": false, "notes": "why this case is tricky"}
```
50 cases across six categories. Questions are worded the way a business user would ask
them. They state which columns to return (results are compared by value) but never hint at
the trap: "Which USD account has the highest balance?", not "...if several tie, return all".

Baseline (Haiku 5.5, prompt v1, effort `medium`): **92–94%**. Identical runs vary by
about one case. The misses are ties (q046, q047, q050) and the empty months (q040).

`tests/test_golden.py` checks the cases themselves: each gold query runs, a
known-wrong query **fails** each case (proving the trap works), and an
alternative correct query **passes** it (proving the grader isn't too strict).

## Graders
- `evals/graders/executes.py`: `run_sql()` / `executes()`. Does the SQL run? Read-only
  connection (generated SQL can't modify data) and a 5s timeout.
- `evals/graders/exec_match.py`: `results_match()` / `exec_match()`. Same result set as gold?
  - row order ignored unless `order_matters`
  - column names ignored, column **order** matters
  - numbers rounded to 4 dp; `5 == 5.0`; `NULL == NULL` but `NULL != 0`
  - duplicate rows are counted (multiset comparison)
  - errors and timeouts fail
