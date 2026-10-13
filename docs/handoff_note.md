# Handoff: analytics-ready starter data

## Ready datasets

The local SQLite file contains current-state appointment, claim, and support
facts joined by stable synthetic patient/provider IDs, plus date dimensions.
Use `fact_record_history` to inspect accepted source revisions and
`dq_results` for the checks run at the latest pipeline execution. Each source
batch also has a staging CSV and a JSONL quarantine file with rejection reasons.

## Safe uses and risks

Use for dashboard prototyping, SQL practice, metadata shape exploration, and
synthetic workflow/model-feature prototypes only. IDs and values are fictional.
Do not interpret the synthetic rates or amounts as hospital performance, train
or validate a clinical model on these records, or connect this database to
production systems. A claim can reference an appointment not present in the
appointment fact table; that optional relationship is not currently enforced.

## Not production ready

This is a single-process local SQLite demonstration with small batch files.
It has no access controls, encryption, retention policy, operational alerting,
or validated clinical/business definitions. The pseudonymous IDs are synthetic,
not a demonstrated anonymization method. Before any real-data use, obtain
privacy/security/legal review and design for Saudi data-residency and PDPL
obligations, least-privilege access, encryption, auditing, retention, and
incident response.
