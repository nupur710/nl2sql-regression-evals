# LLM judge vs execution grading

Judge: `claude-sonnet-5-5` (effort `medium`, prompt `v1`). Items: 100 (gold + trap queries). Run: 2026-11-11T16:20:09+00:00.

| Metric | Value |
|---|---|
| Accuracy (agreement with execution) | 96.0% |
| Cohen's kappa | 0.920 |
| Fooled: wrong SQL judged correct | 4 of 50 (8.0%) |
| Too strict: right SQL judged wrong | 0 of 50 (0.0%) |
| No verdict | 0 |

|  | Execution: correct | Execution: wrong |
|---|---|---|
| **Judge: correct** | 50 | 4 |
| **Judge: wrong** | 0 | 46 |

### Accuracy by category

| Category | Accuracy |
|---|---|
| aggregation | 100.0% |
| ambiguity | 100.0% |
| date | 94.4% |
| join | 100.0% |
| null_handling | 100.0% |
| trap | 75.0% |

### Where the judge was fooled (wrong SQL it passed)

| Item | Category | Execution says | Judge's reasoning |
|---|---|---|---|
| q040:trap | date | row_count_mismatch | The query filters to created_at starting with '2024', which covers both date and datetime formats, groups by the year-month string, and counts rows. It returns only months that have transactions, which is reasonable since the question doesn't ask for zero-count months. No ordering is required. |
| q046:trap | trap | row_count_mismatch | The query filters to USD accounts, orders by balance descending, and returns the top account_id. This answers the question. Ties are possible but the question asks for a single account, and closed accounts are not excluded by the question. |
| q047:trap | trap | row_count_mismatch | The query groups by currency and selects t.account_id alongside MAX(t.amount). SQLite's bare-column extension with a single MAX aggregate returns the account_id from the row that has the max value, so it correctly identifies the account with the largest deposit per currency. Ties would pick an arbitrary row, but that's an ambiguity in the question itself. The filters on deposit and completed are correct, and the output columns are currency and account_id as requested. |
| q050:trap | trap | row_count_mismatch | The query counts completed transactions per user via the accounts join, orders by count descending, and takes the second row with OFFSET 1. This is correct unless ties exist, where the answer is ambiguous anyway. The question asks for 'the user with second-highest number', and this is the standard interpretation. |

### Where the judge was too strict (right SQL it failed)

None.
