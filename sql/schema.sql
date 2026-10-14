PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS dim_patient (
    patient_id TEXT PRIMARY KEY,
    patient_key TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS dim_provider (
    provider_id TEXT PRIMARY KEY,
    provider_key TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS dim_date (
    date_key TEXT PRIMARY KEY,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    day INTEGER NOT NULL,
    weekday INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS fact_appointment (
    appointment_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES dim_patient(patient_id),
    provider_id TEXT NOT NULL REFERENCES dim_provider(provider_id),
    appointment_at TEXT NOT NULL,
    event_date TEXT NOT NULL REFERENCES dim_date(date_key),
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    record_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS fact_claim (
    claim_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES dim_patient(patient_id),
    provider_id TEXT NOT NULL REFERENCES dim_provider(provider_id),
    appointment_id TEXT,
    amount REAL NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    record_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS fact_support_interaction (
    interaction_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES dim_patient(patient_id),
    provider_id TEXT NOT NULL REFERENCES dim_provider(provider_id),
    opened_at TEXT NOT NULL,
    opened_date TEXT NOT NULL REFERENCES dim_date(date_key),
    closed_at TEXT,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    record_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS fact_record_history (
    history_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    business_key TEXT NOT NULL,
    record_version INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    row_number INTEGER NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS processed_batches (
    batch_id TEXT PRIMARY KEY,
    file_hash TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    staged_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS dq_results (
    dq_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL DEFAULT '',
    check_name TEXT NOT NULL,
    passed INTEGER NOT NULL,
    details TEXT NOT NULL,
    checked_at TEXT NOT NULL
);
