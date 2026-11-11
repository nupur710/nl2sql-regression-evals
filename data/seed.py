"""Build the deterministic fintech SQLite database used by the evals.

Two kinds of rows:
  * Hand-written rows (users, accounts, assets, and a few special transactions)
    so every trap the golden cases rely on is guaranteed to exist.
  * Generated transactions from a fixed-seed random generator, so there is
    enough volume for aggregations while staying identical on every run.

Run:  python -m data.seed          (writes data/fintech.db)
"""

import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = DATA_DIR / "schema.sql"
DEFAULT_DB_PATH = DATA_DIR / "fintech.db"

SEED = 42
END_OF_DATA = datetime(2026, 6, 30, 23, 59, 59)
TS_FORMAT = "%Y-%m-%d %H:%M:%S"

# (user_id, full_name, email, country, signup_date, referred_by)
# Traps: users 1 and 3 are both "Alex Kim"; 6, 10, 15 have NULL country;
#        15 and 19 have no accounts.
USERS = [
    (1, "Alex Kim", "alex.kim@example.com", "US", "2024-01-10", None),
    (2, "Priya Shah", "priya.shah@example.com", "IN", "2024-03-01", 1),
    (3, "Alex Kim", "alexk.toronto@example.com", "CA", "2024-04-01", None),
    (4, "Maria Garcia", "maria.garcia@example.com", "ES", "2024-05-15", 2),
    (5, "John Smith", "john.smith@example.com", "US", "2024-05-30", None),
    (6, "Chen Wei", "chen.wei@example.com", None, "2024-06-25", 5),
    (7, "Fatima Noor", "fatima.noor@example.com", "GB", "2024-07-05", None),
    (8, "Lucas Brown", "lucas.brown@example.com", "US", "2024-08-01", 1),
    (9, "Sofia Rossi", "sofia.rossi@example.com", "IT", "2024-08-28", 4),
    (10, "Omar Haddad", "omar.haddad@example.com", None, "2024-09-10", None),
    (11, "Emma Wilson", "emma.wilson@example.com", "GB", "2024-09-28", 7),
    (12, "Kenji Tanaka", "kenji.tanaka@example.com", "JP", "2024-11-01", None),
    (13, "Ana Silva", "ana.silva@example.com", "BR", "2024-11-25", 9),
    (14, "David Lee", "david.lee@example.com", "US", "2025-01-02", None),
    (15, "Nina Patel", "nina.patel@example.com", None, "2025-01-20", 2),
    (16, "Tom Muller", "tom.muller@example.com", "DE", "2025-02-10", None),
    (17, "Grace Okafor", "grace.okafor@example.com", "NG", "2025-03-01", 11),
    (18, "Leo Martin", "leo.martin@example.com", "FR", "2025-04-01", None),
    (19, "Zara Ahmed", "zara.ahmed@example.com", "GB", "2025-04-20", 7),
    (20, "Ivan Petrov", "ivan.petrov@example.com", "US", "2025-05-01", 14),
]

# (account_id, user_id, account_type, currency, opened_at, closed_at, balance)
# Traps: accounts 6, 10, 17, 29 are closed (closed_at set);
#        account 25 is open but has a 0 balance (so "balance > 0" != "open");
#        user 10's only account is closed; accounts 11 and 28 tie for top USD balance.
ACCOUNTS = [
    (1, 1, "checking", "USD", "2024-01-15", None, 2500.00),
    (2, 1, "brokerage", "USD", "2024-02-01", None, 12000.50),
    (3, 2, "savings", "INR", "2024-03-10", None, 150000.00),
    (4, 2, "brokerage", "USD", "2024-03-12", None, 8000.00),
    (5, 3, "checking", "USD", "2024-04-05", None, 1800.25),
    (6, 3, "savings", "USD", "2024-04-05", "2025-06-30", 0.00),
    (7, 4, "checking", "EUR", "2024-05-20", None, 3200.00),
    (8, 4, "brokerage", "EUR", "2024-05-22", None, 5400.00),
    (9, 5, "checking", "USD", "2024-06-01", None, 950.75),
    (10, 5, "savings", "USD", "2024-06-01", "2025-01-15", 0.00),
    (11, 5, "brokerage", "USD", "2024-06-15", None, 22000.00),
    (12, 6, "checking", "USD", "2024-07-01", None, 400.00),
    (13, 7, "brokerage", "GBP", "2024-07-10", None, 7600.00),
    (14, 8, "checking", "USD", "2024-08-08", None, 1250.00),
    (15, 8, "brokerage", "USD", "2024-08-09", None, 3300.00),
    (16, 9, "savings", "EUR", "2024-09-01", None, 9100.00),
    (17, 10, "brokerage", "USD", "2024-09-15", "2025-09-01", 0.00),
    (18, 11, "checking", "GBP", "2024-10-01", None, 2100.00),
    (19, 11, "brokerage", "GBP", "2024-10-02", None, 4400.00),
    (20, 12, "brokerage", "JPY", "2024-11-11", None, 1500000.00),
    (21, 13, "checking", "BRL", "2024-12-01", None, 5000.00),
    (22, 14, "brokerage", "USD", "2025-01-05", None, 15000.00),
    (23, 14, "savings", "USD", "2025-01-05", None, 6000.00),
    (24, 16, "brokerage", "EUR", "2025-02-14", None, 7000.00),
    (25, 17, "checking", "USD", "2025-03-03", None, 0.00),
    (26, 18, "brokerage", "EUR", "2025-04-04", None, 3900.00),
    (27, 20, "checking", "USD", "2025-05-05", None, 700.00),
    (28, 20, "brokerage", "USD", "2025-05-06", None, 22000.00),  # ties account 11
    (29, 12, "savings", "JPY", "2025-06-01", "2026-01-31", 0.00),
    (30, 7, "checking", "GBP", "2025-07-07", None, 1200.00),
]

# (asset_id, symbol, name, asset_class, price)  -- price = latest market price
ASSETS = [
    (1, "AAPL", "Apple Inc.", "equity", 230.50),
    (2, "MSFT", "Microsoft Corp.", "equity", 415.20),
    (3, "TSLA", "Tesla Inc.", "equity", 250.00),
    (4, "VTI", "Vanguard Total Stock Market ETF", "etf", 280.10),
    (5, "BND", "Vanguard Total Bond Market ETF", "etf", 72.40),
    (6, "BTC", "Bitcoin", "crypto", 68000.00),
    (7, "ETH", "Ethereum", "crypto", 3500.00),
    (8, "GLD", "SPDR Gold Shares", "commodity", 210.00),
]

# Listed but never traded. Kept out of ASSETS so the random generator's
# sequence (and therefore every generated transaction) is unchanged.
UNTRADED_ASSETS = [
    (9, "SOL", "Solana", "crypto", 150.00),
]

# Hand-written transactions:
# (account_id, asset_id, txn_type, quantity, price, amount, status, created_at, settled_at)
SPECIAL_TRANSACTIONS = [
    # Month-boundary timestamps: catch BETWEEN '...-01' AND '...-31' bugs.
    (9, None, "deposit", None, None, 500.00, "completed", "2026-03-31 23:59:59", "2026-04-01 09:00:00"),
    (1, None, "deposit", None, None, 250.00, "completed", "2026-03-01 00:00:00", "2026-03-01 08:00:00"),
    (14, None, "withdrawal", None, None, 120.00, "completed", "2026-04-01 00:00:00", "2026-04-01 10:00:00"),
    (7, None, "withdrawal", None, None, 80.00, "failed", "2026-02-28 23:59:59", None),
    # AAPL buys at a historical price far from today's price; one is pending.
    (2, 1, "buy", 10.0, 180.00, 1800.00, "completed", "2025-03-14 10:30:00", "2025-03-15 10:30:00"),
    (22, 1, "buy", 5.0, 205.40, 1027.00, "pending", "2026-06-29 15:00:00", None),
    # Two USD deposits tie for the largest single deposit (generated ones are < 3000).
    (23, None, "deposit", None, None, 3000.00, "completed", "2025-08-12 09:15:00", "2025-08-12 18:00:00"),
    (27, None, "deposit", None, None, 3000.00, "completed", "2025-11-03 14:40:00", "2025-11-04 08:00:00"),
]

# Which transaction types each account type produces, with weights.
TXN_MIX = {
    "checking": [("deposit", 60), ("withdrawal", 40)],
    "savings": [("deposit", 60), ("withdrawal", 40)],
    "brokerage": [("deposit", 20), ("buy", 45), ("sell", 20), ("fee", 15)],
}

# Typical spend per trade by asset class: (low, high).
TRADE_SIZE = {
    "equity": (200, 6000),
    "etf": (100, 3000),
    "crypto": (50, 2000),
    "commodity": (500, 4000),
}


def _parse_date(text):
    return datetime.strptime(text, "%Y-%m-%d")


def _random_timestamp(rng, start, end):
    span_seconds = int((end - start).total_seconds())
    return start + timedelta(seconds=rng.randint(0, span_seconds))


def _status_and_settled(rng, created, txn_type):
    """Fees always complete; other transactions sometimes pend or fail."""
    if txn_type == "fee":
        status = "completed"
    else:
        status = rng.choices(["completed", "pending", "failed"], [85, 8, 7])[0]
    if status != "completed":
        return status, None
    settled = created + timedelta(hours=rng.randint(0, 48))
    return status, settled.strftime(TS_FORMAT)


def _trade_fields(rng, asset):
    """Return (asset_id, quantity, price, amount) for a buy or sell."""
    asset_id, _symbol, _name, asset_class, market_price = asset
    price = round(market_price * rng.uniform(0.6, 1.2), 2)
    target_spend = rng.uniform(*TRADE_SIZE[asset_class])
    if asset_class == "crypto":
        quantity = round(target_spend / price, 4)
    else:
        quantity = float(max(1, round(target_spend / price)))
    return asset_id, quantity, price, round(quantity * price, 2)


def _generate_transaction(rng, account):
    account_id, _user, account_type, _cur, opened_at, closed_at, _bal = account
    start = _parse_date(opened_at)
    end = _parse_date(closed_at) if closed_at else END_OF_DATA
    created = _random_timestamp(rng, start, end)

    types, weights = zip(*TXN_MIX[account_type])
    txn_type = rng.choices(types, weights)[0]

    if txn_type in ("buy", "sell"):
        asset_id, quantity, price, amount = _trade_fields(rng, rng.choice(ASSETS))
    elif txn_type == "fee":
        asset_id, quantity, price, amount = None, None, None, round(rng.uniform(1, 25), 2)
    else:
        asset_id, quantity, price, amount = None, None, None, round(rng.uniform(20, 3000), 2)

    status, settled_at = _status_and_settled(rng, created, txn_type)
    return (account_id, asset_id, txn_type, quantity, price, amount,
            status, created.strftime(TS_FORMAT), settled_at)


def generate_transactions(seed=SEED):
    """All transactions (generated + special), sorted by time, with txn_ids."""
    rng = random.Random(seed)
    rows = []
    for account in ACCOUNTS:
        for _ in range(rng.randint(4, 12)):
            rows.append(_generate_transaction(rng, account))
    rows.extend(SPECIAL_TRANSACTIONS)
    rows.sort(key=lambda row: row[7])  # created_at; sort is stable
    return [(txn_id, *row) for txn_id, row in enumerate(rows, start=1)]


def build_db(db_path=DEFAULT_DB_PATH):
    """Create a fresh database at db_path. Returns the path."""
    db_path = Path(db_path)
    db_path.unlink(missing_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        conn.executemany("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)", USERS)
        conn.executemany("INSERT INTO accounts VALUES (?, ?, ?, ?, ?, ?, ?)", ACCOUNTS)
        conn.executemany("INSERT INTO assets VALUES (?, ?, ?, ?, ?)", ASSETS + UNTRADED_ASSETS)
        conn.executemany(
            "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            generate_transactions(),
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB_PATH
    print(f"Built {build_db(target)}")
