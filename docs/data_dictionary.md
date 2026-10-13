# Data dictionary

| Dataset | Grain / business key | Important columns |
|---|---|---|
| `dim_patient` | One synthetic patient / `patient_id` | `patient_key` is the same stable synthetic ID; no direct identifiers |
| `dim_provider` | One synthetic provider / `provider_id` | `provider_key` is the stable synthetic ID |
| `dim_date` | One UTC calendar day / `date_key` | Year, month, day, weekday |
| `fact_appointment` | Latest appointment / `appointment_id` | Patient/provider keys, UTC `appointment_at`, canonical status, source `updated_at`, record version |
| `fact_claim` | Latest claim / `claim_id` | Patient/provider keys, optional appointment link, nonnegative `amount`, canonical status and version |
| `fact_support_interaction` | Latest ticket / `interaction_id` | Patient/provider keys, open/close UTC timestamps, canonical status and version |
| `fact_record_history` | One accepted source row / `history_id` | Source, business key, record version, update time, batch, source line, JSON payload |
| `processed_batches` | One delivered source file / `batch_id` | SHA-256, raw row count, processing status and time |
| `dq_results` | One check execution / `dq_id` | Check name, pass/fail, details and timestamp |

Rejected rows are JSON Lines in `data/quarantine/<batch>/<source>.jsonl`.
Every row carries a semicolon-separated `reject_reason`; one row can have
multiple reasons. Staging CSVs contain rows that passed row-level validation.
