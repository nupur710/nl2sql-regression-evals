# LLM judge vs execution grading

Judge: `claude-sonnet-5-5` (effort `medium`, prompt `v1`). Items: 50 (agent SQL from m6_v2b_try1.json). Run: 2026-11-11T16:53:45+00:00.

| Metric | Value |
|---|---|
| Accuracy (agreement with execution) | 92.0% |
| Cohen's kappa | 0.729 |
| Fooled: wrong SQL judged correct | 2 of 9 (22.2%) |
| Too strict: right SQL judged wrong | 2 of 41 (4.9%) |
| No verdict | 0 |

|  | Execution: correct | Execution: wrong |
|---|---|---|
| **Judge: correct** | 39 | 2 |
| **Judge: wrong** | 2 | 7 |

### Accuracy by category

| Category | Accuracy |
|---|---|
| aggregation | 100.0% |
| ambiguity | 100.0% |
| date | 88.9% |
| join | 87.5% |
| null_handling | 100.0% |
| trap | 66.7% |

### Where the judge was fooled (wrong SQL it passed)

| Item | Category | Execution says | Judge's reasoning |
|---|---|---|---|
| q046:agent | trap | row_count_mismatch | The query filters to USD accounts, orders by balance descending, and returns the top account_id. This answers the question; ties are unspecified and the question asks for a single account. Closed accounts are not excluded, but the question doesn't ask for that. |
| q050:agent | trap | row_count_mismatch | The query joins users to accounts to transactions, filters completed, counts per user, orders descending, and takes the second row. This correctly gives the user with the second-highest count, aside from tie handling, which the question doesn't specify. Counting by txn_id is correct and there is no join fan-out, since each transaction belongs to one account and each account to one user. |

### Where the judge was too strict (right SQL it failed)

| Item | Category | Execution says | Judge's reasoning |
|---|---|---|---|
| q014:agent | join | match | The query restricts to completed transactions, so it also returns assets that only have pending or failed transactions. Those assets were attempted but arguably not traded; this is ambiguous. However, "never been traded" most naturally means no transactions at all, and a pending or failed attempt is not a trade, so the completed filter is defensible. Still, the reference likely uses any transaction with the asset (buy/sell), so the status filter likely produces extra rows compared to the expected answer. Also, non-trade transactions such as deposits have a null asset_id, so they don't matter here. |
| q038:agent | date | match | The query filters settled_at to March 2026 using a correct half-open range, which handles timestamps. The extra status = 'completed' filter is the concern: the question asks how many transactions settled in March 2026, and a non-null settled_at already indicates settlement. Pending or failed transactions might have settled_at populated, or only completed ones might; the schema doesn't say. Completed is the most plausible status for settled transactions, but the filter is an assumption the question doesn't state. If failed transactions can have a settled_at, the answer would differ. Without a stated link, the safest reading is to count by settled_at alone, so the added filter risks excluding rows and making the count wrong. |
