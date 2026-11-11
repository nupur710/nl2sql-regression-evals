# Caught regression: a "prompt cleanup" that cost 10.7 points

**Summary.** [PR #2](https://github.com/nupur710/nl2sql-regression-evals/pull/2) replaced the
agent's prompt with a shorter "v2". It looked like a sensible cleanup: about 65% fewer input
tokens, readability guidelines, and a finance reporting convention. Unit tests passed.
The eval gate measured a drop from **92.7% to 82.0%** (−10.7 points, against a 4-point limit)
and blocked the merge.

> This regression was simulated on purpose, to test the pipeline end to end. The prompt
> change was written to look like a plausible, approvable PR, not an obviously broken one.

---

## 1. The pull request

`agent/prompts/v2.txt`, made the default with a one-line change:

```text
You write SQLite queries for a fintech analytics team.

Tables:
users(user_id, full_name, email, country, signup_date, referred_by)
accounts(account_id, user_id, account_type, currency, opened_at, closed_at, balance)
assets(asset_id, symbol, name, asset_class, price)
transactions(txn_id, account_id, asset_id, txn_type, quantity, price, amount, status, created_at, settled_at)

Guidelines:
- Keep queries short and readable: prefer simple JOINs and avoid subqueries and CTEs where possible.
- When the question asks for the top or highest item, use ORDER BY ... LIMIT 1.
- Report on completed transactions only, unless the question asks about pending or failed
  ones (pending and failed transactions never moved money).
- Return exactly the columns the question asks for, in the order it asks for them.
- Reply with only the SQL inside a single ```sql code block.
```

Why a reviewer could approve it:

| Change | The case for it |
|---|---|
| Compact column list instead of the full `CREATE TABLE` schema | Fewer tokens on every call |
| "Prefer simple JOINs, avoid subqueries/CTEs" | Generated SQL is easier to read and review |
| "Use ORDER BY ... LIMIT 1 for the top item" | Standard idiom |
| "Completed transactions only" | Matches how finance reports money movement |

One unit test failed: it expected the full schema in the prompt. The fix was a one-line
update to the test's expected string, after which all 282 tests passed. **Unit tests check
structure, not behaviour, so they couldn't catch this.**

## 2. What the gate reported

The CI job evaluated `main` (prompt v1) and the PR (prompt v2) three times each, in the
same job, and posted this on the PR:

| | Base (v1) | Head (v2) |
|---|---|---|
| Pass rate (mean of 3 runs) | **92.7%** | **82.0%** |
| Change | | **−10.7 pts** (limit: −4) |
| Model / effort | Haiku 5.5 / medium | Haiku 5.5 / medium |
| API errors | 0 | 0 |

| Category | Base | Head |
|---|---|---|
| aggregation | 100.0% | 100.0% |
| ambiguity | 100.0% | 100.0% |
| date | 88.9% | **66.7%** |
| join | 100.0% | **87.5%** |
| null_handling | 100.0% | **88.9%** |
| trap | 55.6% | **33.3%** |

Regressed cases (runs passed out of 3):

| Case | Question | Base | Head |
|---|---|---|---|
| q009 | How many transactions were created in March 2026? | 3/3 | 0/3 |
| q010 | For every user, return user_id and the total fees they have paid. | 3/3 | 0/3 |
| q011 | For each user with a USD account, return user_id, the total balance of their USD accounts, and how many transactions those accounts have. | 3/3 | 0/3 |
| q025 | How many transactions are not linked to any asset? | 3/3 | 0/3 |
| q039 | Assume today is 2026-06-30. How many transactions were created in the last 7 days, including today? | 3/3 | 0/3 |
| q050 | Which user has the second-highest number of completed transactions? | 1/3 | 0/3 |

Failing on both sides (existing weaknesses, not caused by this PR): q040, q046, q047.

The check failed and the branch ruleset on `main` (required status check `eval`) blocked the merge.

## 3. Why each case broke

SQL below is from a local run of the same v2 prompt.

**a) The "completed only" convention changed the meaning of questions that never mentioned
status (q009, q011, q025, q039).** Each answer is a valid, sensible-looking query that
answers a different question from the one asked:

```sql
-- q009: "How many transactions were created in March 2026?"
SELECT COUNT(*) FROM transactions
WHERE status = 'completed' AND strftime('%Y-%m', created_at) = '2026-03'   -- drops pending/failed

-- q025: "How many transactions are not linked to any asset?"
SELECT COUNT(*) FROM transactions WHERE asset_id IS NULL AND status = 'completed'
```

**b) The compact schema dropped information the model needed (q010).** The full schema
lists the allowed values, `CHECK (txn_type IN ('deposit', 'withdrawal', 'buy', 'sell', 'fee'))`.
Without that list, the model didn't know fee transactions exist and refused:

```sql
-- Cannot be answered with this schema: there is no fees column or fee table.
```

**c) The `LIMIT 1` rule made a known weakness consistent (q050).** Ties were already a
problem (1/3 on base); the new rule pushed the model to `ORDER BY ... LIMIT 1 OFFSET 1`
every time, which drops one of the two users tied for second.

## 4. What the other checks would have said

| Check | Result on this PR |
|---|---|
| Unit tests | ✅ Passed (after a one-line test update) |
| Token cost | ✅ "Better": input tokens per run 50k → 17k (−65%). Output tokens rose 11k → 14k. Net saving on Haiku: about **$0.002 per 50-question run** |
| LLM judge (Sonnet 5.5) on v2's SQL | ⚠️ Caught 7 of 9 failures, missed 2, and wrongly failed 2 correct queries (kappa 0.73; [report](../reports/judge_on_prompt_v2.md)) |
| Execution-graded eval gate | ❌ **Blocked: −10.7 points** |

The LLM judge did well here because most of the damage is **visible in the SQL**: an
unrequested `status = 'completed'` filter is easy to spot. It again missed the ties
(q046, q050), which can only be seen in the data. On the agent's v1 output, where the failures
were all data-dependent, the same judge caught **none of 4** (kappa 0.00;
[report](../reports/judge_agreement_agent_outputs.md)). An LLM judge's usefulness depends on
*what kind* of mistake is being made; execution grading doesn't.

## 5. A regression the gate would have missed

The first draft of v2 had only the compact schema and the two readability rules, without
the "completed only" convention. Locally it scored 88%, 90% and 90% (mean 89.3%) against a
v1 baseline of 92–94%. That is a **~3.7-point drop: real, but under the 4-point
threshold**, so the gate would most likely have let it through.

That's the cost of the threshold. Identical runs vary by about one case (2 points), so a
tighter limit would block PRs at random. Options if small regressions matter:
- more repeats per side (the noise in the mean shrinks roughly with √runs, so 3 → 12 runs
  halves it), at proportionally higher cost and CI time;
- a second, per-case rule: flag any case that passes 3/3 on base and 0/3 on head, even when
  the overall drop is under the threshold;
- more cases in the categories that matter most, so each case is a smaller share of the score.

## 6. Lessons

1. **Prompt changes need behavioural tests.** The unit tests were updated in one line and
   went green. Only running the agent against graded cases showed what changed.
2. **"Reasonable defaults" silently change answers.** The completed-only rule never broke
   a query; every result looked plausible. Only comparing values against a gold answer exposes it.
3. **Shortening a schema removes meaning, not just tokens.** The allowed values in a
   `CHECK` constraint were the only place the model learned that fees exist.
4. **Report the noise, and size the threshold from it.** The gate is useful because the
   threshold was set from measured run-to-run variance, and because both sides are run
   several times in the same job.
5. **Don't let an LLM judge be the only gate.** It caught this regression but missed every
   data-dependent failure; execution grading caught both kinds.

## Reproduce

```bash
git fetch origin prompt-v2-compact && git checkout prompt-v2-compact
python -m evals.run_eval                       # v2 is the default on this branch
git checkout main && python -m evals.run_eval  # v1 baseline
python -m evals.compare --base results/<v1 run>.json --head results/<v2 run>.json
```
