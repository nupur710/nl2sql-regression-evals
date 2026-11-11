# LLM judge vs execution grading

Judge: `claude-sonnet-5-5` (effort `medium`, prompt `v1`). Items: 50 (agent SQL from m3_v1_reworded_medium.json). Run: 2026-11-11T16:21:25+00:00.

| Metric | Value |
|---|---|
| Accuracy (agreement with execution) | 92.0% |
| Cohen's kappa | 0.000 |
| Fooled: wrong SQL judged correct | 4 of 4 (100.0%) |
| Too strict: right SQL judged wrong | 0 of 46 (0.0%) |
| No verdict | 0 |

|  | Execution: correct | Execution: wrong |
|---|---|---|
| **Judge: correct** | 46 | 4 |
| **Judge: wrong** | 0 | 0 |

### Accuracy by category

| Category | Accuracy |
|---|---|
| aggregation | 100.0% |
| ambiguity | 100.0% |
| date | 88.9% |
| join | 100.0% |
| null_handling | 100.0% |
| trap | 50.0% |

### Where the judge was fooled (wrong SQL it passed)

| Item | Category | Execution says | Judge's reasoning |
|---|---|---|---|
| q040:agent | date | row_count_mismatch | The filter covers all of 2024, including timestamps on Dec 31 with time parts, since they are less than '2025-01-01'. Grouping by strftime month and counting rows gives the correct count per month. Months with zero transactions would be omitted, but that is the normal interpretation of the question. |
| q046:agent | trap | row_count_mismatch | The query filters to USD accounts, sorts by balance descending, and returns the top account_id. This answers the question; ties are unspecified in the question and unlikely to matter. Closed accounts are not excluded, but the question doesn't ask for that. |
| q047:agent | trap | row_count_mismatch | The query joins completed deposits to accounts, ranks by amount descending within each currency, and keeps the top row. This returns one account per currency with its largest single completed deposit. Ties are broken deterministically by txn_id, which is reasonable. Columns are currency and account_id, as requested. |
| q050:agent | trap | row_count_mismatch | The query counts completed transactions per user via accounts, orders by count descending, and takes the second row. Ties are broken by user_id, which is arbitrary but deterministic. If the top two users tie, it returns the second in tie order, which is a reasonable reading. The main ambiguity is whether 'second-highest' means second distinct count value, but the usual interpretation is the second-ranked user, so the query is likely correct. |

### Where the judge was too strict (right SQL it failed)

None.
