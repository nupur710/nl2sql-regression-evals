-- Fintech sample schema for the SQL agent evals.
--
-- Conventions:
--   * Dates are ISO-8601 TEXT: 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'.
--   * transactions.amount and transactions.quantity are always positive;
--     txn_type gives the direction.
--   * Money is in the account's own currency (no FX conversion).

CREATE TABLE users (
    user_id     INTEGER PRIMARY KEY,
    full_name   TEXT    NOT NULL,
    email       TEXT    NOT NULL UNIQUE,
    country     TEXT,                       -- ISO country code
    signup_date TEXT    NOT NULL,
    referred_by INTEGER REFERENCES users(user_id)
);

CREATE TABLE accounts (
    account_id   INTEGER PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(user_id),
    account_type TEXT    NOT NULL CHECK (account_type IN ('checking', 'savings', 'brokerage')),
    currency     TEXT    NOT NULL,          -- ISO currency code
    opened_at    TEXT    NOT NULL,
    closed_at    TEXT,
    balance      REAL    NOT NULL
);

CREATE TABLE assets (
    asset_id    INTEGER PRIMARY KEY,
    symbol      TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    asset_class TEXT NOT NULL,              -- equity, etf, crypto, commodity
    price       REAL NOT NULL               -- latest market price per unit
);

CREATE TABLE transactions (
    txn_id     INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(account_id),
    asset_id   INTEGER REFERENCES assets(asset_id),
    txn_type   TEXT    NOT NULL CHECK (txn_type IN ('deposit', 'withdrawal', 'buy', 'sell', 'fee')),
    quantity   REAL,
    price      REAL,
    amount     REAL    NOT NULL,
    status     TEXT    NOT NULL CHECK (status IN ('completed', 'pending', 'failed')),
    created_at TEXT    NOT NULL,
    settled_at TEXT
);
