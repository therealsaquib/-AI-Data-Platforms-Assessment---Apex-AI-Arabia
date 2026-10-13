# AI/tool disclosure

- Tools used: I used Claude and a VS Code agent (Copilot SDK in VS Code) to draft project files and run checks. Environment: Python 3.12.6, SQLite 3.45.3, pandas 3.0.6, pytest 9.1.1, Faker 39.1.0, PyYAML 6.0.3; DuckDB is not used.
- What I personally reviewed, changed, and can explain: I read `sql/` and `data/` line by line. I named `src/`, `tests/`, and `config.yaml` as reviewed but did not specify review depth. I added `data/` and wrote code in `src/` to meet the assessment requirements. I can explain the data and SQL. Beyond automated tests, I edited a source column, delivered a batch twice, and changed/ran a SQL query. I have not itemized other hand edits or my understanding of each implementation detail.
- Commands/tests I ran and their actual outcomes: On 2026-10-13 at 15:24 +05:30, in a clean temporary copy, I ran `python -m venv .venv`, `.\.venv\Scripts\Activate.ps1`, `python -m pip install -r requirements.txt`, `python --version`, and `python -m pip list`; setup succeeded (Python 3.12.6). `python -m src.pipeline` ran three times, each exit 0. Run 1 read 321/261/301 day-one and 25/16/12 day-two scheduling/claims/support rows; all runs reported curated counts 317/256/296 and `day2_repeat_unchanged=True`. `python -m pytest` exited 0: 8 passed in 2.24s. `python -m src.pipeline --fail-demo` exited 0 with `EXPECTED CONTROLLED FAILURE: 1 data-quality check(s) failed: accepted_statuses`. `python -m src.pipeline --schema-drift-demo` exited 0 with unmapped `appointment_time_new_unknown` and a config-mapping suggestion. Both demos catch and print their expected failures.
- What I could not independently validate: Real-world behavior and million-row/day performance were not tested; Python 3.11 was not tested. The DQ demo fails only the accepted-status check; I did not force every rule to fail. Some tests are smoke-level (config keys, JSON reading, schema columns). Access control, monitoring, orchestration, and Saudi PDPL/data residency are not implemented.
- Any generated code or text I adapted: AI-assisted: `src/generate_data.py`, `src/ingest.py`, `src/transform.py`, `src/quality_checks.py`, `src/load.py`, `src/pipeline.py`, `src/logger.py`, `sql/schema.sql`, `sql/analysis.sql`, `tests/test_pipeline.py`, `README.md`, `docs/handoff_note.md`, and `docs/diagram.md`, plus config/supporting docs. No Kaggle rows or external code/tutorial text were used in the AI-assisted work visible here; I cannot establish whether I separately used any. I cannot separate Claude's individual contributions.

## Data safety statement

I searched project text, including raw/staging/quarantine, for credential patterns, common personal-identifier fields, and confidential-source markers. No credentials or personal-identifier patterns were found. The data contains generated synthetic IDs/records; I found no real patient/customer data or employer-confidential material. “Real patient” appears only in documentation about limitations.

## Known gaps vs the assessment brief

- The runner regenerates two fixed batches instead of accepting arbitrary daily deliveries. The schema-drift demo also regenerates raw files in the project root, despite docs saying demos use a temporary tree.
- `docs/data_issues.md` says lowercase `canceled` is planted; I did not find it in raw scheduling rows.
- Schema/type DQ covers selected columns only. Latest-DQ SQL selects by timestamp, not run ID; it returned 15 rows in one audit, although the three clean runs returned 16.

Do not claim personal verification of work you have not run or understood.
