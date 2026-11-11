# LLM judge vs execution grading

Judge: `claude-haiku-5-5` (effort `medium`, prompt `v1`). Items: 100 (gold + trap queries). Run: 2026-11-11T16:20:54+00:00.

| Metric | Value |
|---|---|
| Accuracy (agreement with execution) | 93.0% |
| Cohen's kappa | 0.860 |
| Fooled: wrong SQL judged correct | 5 of 50 (10.0%) |
| Too strict: right SQL judged wrong | 2 of 50 (4.0%) |
| No verdict | 0 |

|  | Execution: correct | Execution: wrong |
|---|---|---|
| **Judge: correct** | 48 | 5 |
| **Judge: wrong** | 2 | 45 |

### Accuracy by category

| Category | Accuracy |
|---|---|
| aggregation | 100.0% |
| ambiguity | 88.9% |
| date | 94.4% |
| join | 93.8% |
| null_handling | 100.0% |
| trap | 75.0% |

### Where the judge was fooled (wrong SQL it passed)

| Item | Category | Execution says | Judge's reasoning |
|---|---|---|---|
| q031:trap | ambiguity | row_count_mismatch | The query joins transactions to accounts and assets, filters for asset name 'Apple', txn_type 'buy', and status 'completed', and selects DISTINCT user_id, which matches 'users who have completed at least one buy of Apple stock'. The filter uses s.name = 'Apple' rather than the symbol, which is a reasonable reading of 'Apple stock'; the only risk is whether the asset name is exactly 'Apple' in the data, which cannot be verified from the schema alone. |
| q040:trap | date | row_count_mismatch | The query groups transactions by strftime('%Y-%m', created_at), producing 'YYYY-MM' labels, and counts rows per group. The filter created_at LIKE '2024%' correctly restricts to 2024 since dates are ISO-8601 text starting with the year. No status filter is required by the question, so counting all transactions is appropriate. |
| q046:trap | trap | row_count_mismatch | The query filters accounts to currency 'USD', orders by balance descending, and takes the top row, which returns the account_id with the highest USD balance. The question does not restrict to open accounts or any other condition, so no additional filtering is needed. Ties are not specified, and the single-row result matches the question's request. |
| q047:trap | trap | row_count_mismatch | The query filters to completed deposits, joins accounts for currency, and groups by currency. SQLite's bare-column behavior with a single MAX() aggregate returns account_id from the row holding the maximum amount, so the outer SELECT yields one (currency, account_id) pair per currency. The unaliased subquery is valid in SQLite. |
| q050:trap | trap | row_count_mismatch | The derived table correctly counts completed transactions per user by joining through accounts, and the outer query orders by that count and takes the second row with OFFSET 1. The unaliased subquery is valid in SQLite, and the outer ORDER BY can reference n. The only ambiguity is ties at the top, which the question does not address, so the query is judged correct. |

### Where the judge was too strict (right SQL it failed)

| Item | Category | Execution says | Judge's reasoning |
|---|---|---|---|
| q008:gold | ambiguity | match | The query sums balances across all of Alex Kim's accounts, including those with a non-null closed_at. A 'total account balance' most plausibly means currently held money, so closed accounts should be excluded, and the query does not do that. The result is therefore likely wrong unless closed accounts always carry zero balance, which the schema does not guarantee. |
| q014:gold | join | match | The question asks for assets never traded, which means no buy or sell transactions reference them. The query checks for any transaction with matching asset_id, regardless of txn_type, so an asset with only a 'deposit', 'fee', or 'withdrawal' row (which would typically have asset_id NULL, but could be set) would be excluded even though it was never traded. Whether this matters depends on whether non-trade transactions carry asset_id; the schema allows asset_id on any transaction, so the query may miss assets that were never bought or sold. |
