# Controlled failure investigation paths

Both commands are intentionally expected to fail within an isolated temporary
directory and report an `EXPECTED CONTROLLED FAILURE` message. Neither edits
the normal `data/curated/assessment.db`.

## 1. Unmapped source column

Run `python -m src.pipeline --schema-drift-demo`. The demo changes one header
to an unrecognized name and exercises `SchemaDriftError`.

1. Record the reported source and exact unmapped header.
2. Compare it with the delivered CSV/JSON and confirm its meaning with the
   source owner; do not map by guesswork.
3. Add the observed normalized header under `columns.<source>` in
   `config.yaml`, targeting the existing canonical field.
4. Add/adjust a mapping test, regenerate the input, then rerun the demo and
   normal pipeline. A genuinely changed schema needs an explicit contract
   review before adding an alias.

## 2. Curated data-quality violation

Run `python -m src.pipeline --fail-demo`. The demo injects an unaccepted
appointment status into a temporary curated database and exercises
`DQFailureError`.

1. Read the exact failed check and offending normalized value from the console
   output. In a normal run, use `logs/pipeline.log` and the matching
   `dq_results` row as the durable run evidence.
2. Inspect the responsible curated rows, their accepted `fact_record_history`
   payloads, staging CSV and the related quarantine JSONL.
3. Decide whether the source value is a legitimate new business state or bad
   data with the product/source owner. Add a status mapping only if confirmed;
   otherwise fix upstream or quarantine the invalid row.
4. Update a focused test, rerun the failure demo, then verify the regular
   pipeline passes. Do not simply weaken the check to make it green.
