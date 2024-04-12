CREATE TABLE accounts (
    account_id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT
);

CREATE TABLE transactions (
    transaction_id SERIAL PRIMARY KEY,
    debit_account_id INTEGER REFERENCES accounts(account_id),
    credit_account_id INTEGER REFERENCES accounts(account_id),
    amount NUMERIC(10,2) NOT NULL,
    description TEXT,
    CHECK (amount > 0),
    CHECK (debit_account_id != credit_account_id)
);

CREATE TABLE balances (
    account_id INTEGER PRIMARY KEY REFERENCES accounts(account_id),
    balance NUMERIC(10,2)
);
