import csv
import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from src.generate_data import generate_data
from src.ingest import SchemaDriftError, canonicalize_headers, load_config, read_records
from src.load import connect, load_entities, load_rows
from src.logger import close_logger, make_logger
from src.pipeline import QuarantineThresholdError, _run_single_batch, process_batch
from src.quality_checks import DQFailureError, run_quality_checks
from src.transform import normalize_status, parse_timestamp, transform_rows


ROOT = Path(__file__).resolve().parents[1]


def test_status_normalization_handles_case_variants():
    assert normalize_status("CANCELED", {"canceled": "cancelled"}) == "cancelled"


def test_open_support_ticket_without_closed_at_is_valid():
    config = load_config(ROOT / "config.yaml")
    entities = {"patients": ["PAT0001"], "providers": ["PRV001"]}
    row = {
        "interaction_id": "TKT00001", "patient_id": "PAT0001", "provider_id": "PRV001",
        "opened_at": "2026-09-01T00:00:00+00:00", "closed_at": "",
        "status": "Open", "updated_at": "2026-09-01T00:00:00+00:00",
    }
    valid, rejected = transform_rows([row], "support", config, entities)
    assert len(valid) == 1
    assert rejected == []


def test_resolved_support_ticket_without_closed_at_is_quarantined():
    config = load_config(ROOT / "config.yaml")
    entities = {"patients": ["PAT0001"], "providers": ["PRV001"]}
    row = {
        "interaction_id": "TKT00001", "patient_id": "PAT0001", "provider_id": "PRV001",
        "opened_at": "2026-09-01T00:00:00+00:00", "closed_at": "",
        "status": "resolved", "updated_at": "2026-09-01T00:00:00+00:00",
    }
    valid, rejected = transform_rows([row], "support", config, entities)
    assert valid == []
    assert rejected[0]["reject_reason"] == "invalid_closed_at"


def test_generator_leaves_open_tickets_unclosed_and_plants_resolved_defect(tmp_path):
    raw = generate_data(ROOT / "config.yaml", tmp_path)
    rows = read_records(raw / "batch_day1" / "support.csv", "support")
    open_rows = [row for row in rows if row["resolution_status"].lower() in {"open", "in progress"}]
    resolved_rows = [row for row in rows if row["resolution_status"].lower() in {"closed", "resolved"}]
    assert open_rows and all(not row["closed_at"] for row in open_rows)
    assert any(not row["closed_at"] for row in resolved_rows)


def test_timestamp_parser_returns_utc_iso_and_rejects_invalid():
    assert parse_timestamp("2026-09-01T00:00:00-04:00") == "2026-09-01T04:00:00+00:00"
    assert parse_timestamp("not a date") is None


def test_config_loads_expected_sections():
    config = load_config(ROOT / "config.yaml")
    assert {"paths", "columns", "required_columns", "statuses", "thresholds"} <= config.keys()


def test_known_renamed_column_maps_and_unknown_column_fails():
    config = load_config(ROOT / "config.yaml")
    row = {
        "appointment_id": "APT00001", "patient_id": "PAT0001", "provider_id": "PRV001",
        "scheduled_at": "2026-09-01", "status": "scheduled", "updated_at": "2026-09-01",
    }
    assert canonicalize_headers([row], "scheduling", config)[0]["appointment_time"] == "2026-09-01"
    with pytest.raises(SchemaDriftError, match="config.yaml"):
        canonicalize_headers([dict(row, appointment_time_new_unknown="2026-09-01")], "scheduling", config)


def test_unknown_column_in_later_json_row_is_schema_drift(tmp_path):
    config = load_config(ROOT / "config.yaml")
    raw = generate_data(ROOT / "config.yaml", tmp_path)
    claims = read_records(raw / "batch_day1" / "claims.json", "claims")
    claims[1]["new_unmapped_field"] = "unexpected"
    with pytest.raises(SchemaDriftError, match="new_unmapped_field"):
        canonicalize_headers(claims[:2], "claims", config)


def test_missing_required_canonical_column_is_schema_drift():
    config = load_config(ROOT / "config.yaml")
    row = {
        "appointment_id": "APT00001", "patient_id": "PAT0001", "provider_id": "PRV001",
        "status": "scheduled", "updated_at": "2026-09-01",
    }
    with pytest.raises(SchemaDriftError, match="appointment_time"):
        canonicalize_headers([row], "scheduling", config)


def test_new_status_warns_and_is_written_to_quarantine(tmp_path, caplog):
    config = load_config(ROOT / "config.yaml")
    raw = generate_data(ROOT / "config.yaml", tmp_path)
    source_path = raw / "batch_day1" / "scheduling.csv"
    records = read_records(source_path, "scheduling")
    records[0]["status"] = "New Workflow State"
    with source_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    entities = json.loads((tmp_path / "data" / "reference.json").read_text(encoding="utf-8"))
    connection = connect(tmp_path / "new_status.sqlite", ROOT / "sql" / "schema.sql")
    load_entities(connection, entities)
    logger = make_logger(tmp_path / "logs", "new-status-test")
    try:
        process_batch("batch_day1", raw / "batch_day1", config, entities, connection, logger, tmp_path)
        assert any(
            "unrecognized_status_count=1" in record.message
            and "New Workflow State" in record.message
            for record in caplog.records
        )
        quarantined = [
            json.loads(line)
            for line in (
                tmp_path / config["paths"]["quarantine"] / "batch_day1" / "scheduling.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        assert any(
            row["appointment_id"] == "APT00001"
            and "unrecognized_status" in row["reject_reason"]
            for row in quarantined
        )
    finally:
        connection.close()
        close_logger(logger)


def test_quarantine_rate_over_threshold_raises_with_reasons(tmp_path):
    config = load_config(ROOT / "config.yaml")
    config["thresholds"]["max_quarantine_rate"] = 0.001
    raw = generate_data(ROOT / "config.yaml", tmp_path)
    entities = json.loads((tmp_path / "data" / "reference.json").read_text(encoding="utf-8"))
    connection = connect(tmp_path / "threshold.sqlite", ROOT / "sql" / "schema.sql")
    load_entities(connection, entities)
    logger = make_logger(tmp_path / "logs", "threshold-test")
    try:
        with pytest.raises(
            QuarantineThresholdError,
            match=r"batch_day1, source scheduling: quarantine rate .* top reject reasons=",
        ):
            process_batch("batch_day1", raw / "batch_day1", config, entities, connection, logger, tmp_path)
        ledger = connection.execute(
            "SELECT rejected_count, status FROM processed_batches WHERE batch_id='batch_day1:scheduling'"
        ).fetchone()
        quarantine_file = tmp_path / config["paths"]["quarantine"] / "batch_day1" / "scheduling.jsonl"
        assert len(quarantine_file.read_text(encoding="utf-8").splitlines()) == ledger[0]
        assert ledger[1] == "failed"
    finally:
        connection.close()
        close_logger(logger)


def test_dedupe_upsert_keeps_newest_and_audits_each_record(tmp_path):
    connection = connect(tmp_path / "db.sqlite", ROOT / "sql" / "schema.sql")
    entities = {"patients": ["PAT0001"], "providers": ["PRV001"]}
    load_entities(connection, entities)
    older = {
        "appointment_id": "APT00001", "patient_id": "PAT0001", "provider_id": "PRV001",
        "appointment_time": "2026-09-01T00:00:00+00:00", "status": "scheduled",
        "updated_at": "2026-09-01T00:00:00+00:00", "source_row_number": 2,
    }
    newer = dict(older, status="rescheduled", updated_at="2026-09-02T00:00:00+00:00", source_row_number=3)
    load_rows(connection, "scheduling", [newer, older], "test_batch")
    assert connection.execute("SELECT status FROM fact_appointment").fetchone()[0] == "rescheduled"
    assert connection.execute("SELECT COUNT(*) FROM fact_record_history").fetchone()[0] == 2
    connection.close()


def test_connect_adds_run_id_to_existing_dq_table(tmp_path):
    database = tmp_path / "legacy.sqlite"
    legacy = sqlite3.connect(database)
    legacy.execute(
        "CREATE TABLE dq_results (dq_id INTEGER PRIMARY KEY, check_name TEXT, "
        "passed INTEGER, details TEXT, checked_at TEXT)"
    )
    legacy.commit()
    legacy.close()

    connection = connect(database, ROOT / "sql" / "schema.sql")
    try:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(dq_results)").fetchall()
        }
        assert "run_id" in columns
    finally:
        connection.close()


def test_same_batch_file_hash_is_stable_and_rows_are_processed_once(tmp_path):
    config = load_config(ROOT / "config.yaml")
    raw = generate_data(ROOT / "config.yaml", tmp_path)
    entities = json.loads((tmp_path / "data" / "reference.json").read_text(encoding="utf-8"))
    connection = connect(tmp_path / "db.sqlite", ROOT / "sql" / "schema.sql")
    load_entities(connection, entities)
    logger = make_logger(tmp_path / "logs", "test-run")
    try:
        process_batch("batch_day1", raw / "batch_day1", config, entities, connection, logger, tmp_path)
        first_counts = connection.execute(
            "SELECT COUNT(*) FROM fact_appointment"
        ).fetchone()[0]
        first_history = connection.execute(
            "SELECT COUNT(*) FROM fact_record_history"
        ).fetchone()[0]
        process_batch("batch_day1", raw / "batch_day1", config, entities, connection, logger, tmp_path)
        assert connection.execute("SELECT COUNT(*) FROM fact_appointment").fetchone()[0] == first_counts
        assert connection.execute("SELECT COUNT(*) FROM fact_record_history").fetchone()[0] == first_history
        assert connection.execute("SELECT COUNT(*) FROM processed_batches").fetchone()[0] == 3
    finally:
        connection.close()
        close_logger(logger)


def test_source_rows_can_be_read_from_json_claim_batch(tmp_path):
    raw = generate_data(ROOT / "config.yaml", tmp_path)
    claims = read_records(raw / "batch_day1" / "claims.json", "claims")
    assert len(claims) >= 200
    assert claims[0]["claim_id"].startswith("CLM")


def test_database_declares_star_fact_keys(tmp_path):
    connection = connect(tmp_path / "db.sqlite", ROOT / "sql" / "schema.sql")
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(fact_appointment)").fetchall()
    }
    assert {"appointment_id", "patient_id", "provider_id", "event_date", "status"} <= columns
    connection.close()


def test_custom_batch_folder_processes_with_caller_batch_id(tmp_path):
    config = load_config(ROOT / "config.yaml")
    raw = generate_data(ROOT / "config.yaml", tmp_path)
    config["thresholds"]["minimum_rows"] = {"scheduling": 0, "claims": 0, "support": 0}
    config_path = tmp_path / "custom_config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    _run_single_batch(
        raw / "batch_day2",
        "customer_delivery_001",
        config_path=config_path,
        root=tmp_path,
    )

    connection = connect(tmp_path / config["paths"]["database"], ROOT / "sql" / "schema.sql")
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM processed_batches WHERE batch_id LIKE 'customer_delivery_001:%'"
        ).fetchone()[0] == 3
    finally:
        connection.close()


def _load_two_demo_batches(tmp_path):
    config = load_config(ROOT / "config.yaml")
    raw = generate_data(ROOT / "config.yaml", tmp_path)
    entities = json.loads((tmp_path / "data" / "reference.json").read_text(encoding="utf-8"))
    connection = connect(tmp_path / "dq.sqlite", ROOT / "sql" / "schema.sql")
    load_entities(connection, entities)
    logger = make_logger(tmp_path / "logs", "duplicate-dq-test")
    for batch in ("batch_day1", "batch_day2"):
        process_batch(batch, raw / batch, config, entities, connection, logger, tmp_path)
    return config, connection, logger


def test_duplicate_history_keys_pass_when_current_facts_are_unique(tmp_path):
    config, connection, logger = _load_two_demo_batches(tmp_path)
    try:
        results = run_quality_checks(connection, logger, config, "clean-history-test")
        duplicate_check = next(result for result in results if result["check_name"] == "duplicate_detection")
        assert duplicate_check["passed"] is True
    finally:
        connection.close()
        close_logger(logger)


def test_duplicate_current_fact_row_fails_duplicate_detection(tmp_path):
    config, connection, logger = _load_two_demo_batches(tmp_path)
    try:
        connection.executescript(
            "CREATE TABLE duplicated_appointments AS SELECT * FROM fact_appointment;"
            "DROP TABLE fact_appointment;"
            "ALTER TABLE duplicated_appointments RENAME TO fact_appointment;"
            "INSERT INTO fact_appointment SELECT * FROM fact_appointment LIMIT 1;"
        )
        with pytest.raises(DQFailureError, match="duplicate_detection"):
            run_quality_checks(connection, logger, config, "duplicated-current-test")
        failed = connection.execute(
            "SELECT passed FROM dq_results WHERE check_name='duplicate_detection' ORDER BY dq_id DESC LIMIT 1"
        ).fetchone()
        assert failed == (0,)
    finally:
        connection.close()
        close_logger(logger)


def test_latest_dq_query_returns_all_checks_from_one_run(tmp_path):
    config, connection, logger = _load_two_demo_batches(tmp_path)
    try:
        results = run_quality_checks(connection, logger, config, "latest-results-test")
        latest = connection.execute(
            "SELECT check_name, passed, details, checked_at FROM dq_results "
            "WHERE run_id = (SELECT run_id FROM dq_results ORDER BY dq_id DESC LIMIT 1) "
            "ORDER BY check_name"
        ).fetchall()
        assert len(latest) == len(results)
    finally:
        connection.close()
        close_logger(logger)


def _remove_primary_key_and_duplicate(connection, table):
    broken = f"unconstrained_{table}"
    connection.executescript(
        f"CREATE TABLE {broken} AS SELECT * FROM {table};"
        f"DROP TABLE {table};"
        f"ALTER TABLE {broken} RENAME TO {table};"
        f"INSERT INTO {table} SELECT * FROM {table} LIMIT 1;"
    )


def _inject_dq_violation(check_name, connection, config):
    if check_name in {"appointments_unique", "claims_unique", "support_unique", "duplicate_detection"}:
        table = {
            "appointments_unique": "fact_appointment",
            "claims_unique": "fact_claim",
            "support_unique": "fact_support_interaction",
            "duplicate_detection": "fact_appointment",
        }[check_name]
        _remove_primary_key_and_duplicate(connection, table)
    elif check_name == "facts_not_null":
        connection.executescript(
            "CREATE TABLE unconstrained_appointments AS SELECT * FROM fact_appointment;"
            "DROP TABLE fact_appointment;"
            "ALTER TABLE unconstrained_appointments RENAME TO fact_appointment;"
            "UPDATE fact_appointment SET appointment_id=NULL WHERE rowid=(SELECT MIN(rowid) FROM fact_appointment);"
        )
    elif check_name in {"patient_references", "provider_references", "date_references"}:
        connection.execute("PRAGMA foreign_keys = OFF")
        column = {
            "patient_references": "patient_id",
            "provider_references": "provider_id",
            "date_references": "event_date",
        }[check_name]
        connection.execute(
            f"UPDATE fact_appointment SET {column}='MISSING_REFERENCE' "
            "WHERE rowid=(SELECT MIN(rowid) FROM fact_appointment)"
        )
        connection.execute("PRAGMA foreign_keys = ON")
    elif check_name == "history_completeness":
        connection.execute(
            "DELETE FROM fact_record_history WHERE history_id=(SELECT MIN(history_id) FROM fact_record_history)"
        )
    elif check_name == "resolved_support_has_closed_at":
        connection.execute(
            "UPDATE fact_support_interaction SET closed_at=NULL WHERE status='resolved'"
        )
    elif check_name == "accepted_statuses":
        connection.execute("UPDATE fact_appointment SET status='not_accepted'")
    elif check_name == "timestamp_range":
        connection.execute("UPDATE fact_appointment SET appointment_at='1900-01-01T00:00:00+00:00'")
    elif check_name == "claim_amounts":
        connection.execute("UPDATE fact_claim SET amount=-1")
    elif check_name.endswith("_minimum_row_count"):
        source = check_name.removesuffix("_minimum_row_count")
        config["thresholds"]["minimum_rows"][source] = 10000
    elif check_name == "schema_and_type_validation":
        connection.executescript(
            "CREATE TABLE wrong_type_appointments ("
            "appointment_id TEXT, patient_id TEXT, provider_id TEXT, appointment_at INTEGER, "
            "event_date TEXT, status TEXT, updated_at TEXT, record_version INTEGER);"
            "INSERT INTO wrong_type_appointments SELECT * FROM fact_appointment;"
            "DROP TABLE fact_appointment;"
            "ALTER TABLE wrong_type_appointments RENAME TO fact_appointment;"
        )
    else:
        raise AssertionError(f"No violation injector for {check_name}")


@pytest.mark.parametrize(
    "check_name",
    [
        "appointments_unique",
        "claims_unique",
        "support_unique",
        "facts_not_null",
        "patient_references",
        "provider_references",
        "date_references",
        "duplicate_detection",
        "history_completeness",
        "resolved_support_has_closed_at",
        "accepted_statuses",
        "timestamp_range",
        "claim_amounts",
        "scheduling_minimum_row_count",
        "claims_minimum_row_count",
        "support_minimum_row_count",
        "schema_and_type_validation",
    ],
)
def test_each_dq_check_fails_for_an_injected_violation(check_name, tmp_path):
    config, connection, logger = _load_two_demo_batches(tmp_path)
    try:
        _inject_dq_violation(check_name, connection, config)
        with pytest.raises(DQFailureError, match=check_name):
            run_quality_checks(connection, logger, config, f"violation-{check_name}")
        failed = connection.execute(
            "SELECT passed FROM dq_results WHERE run_id=? AND check_name=? ORDER BY dq_id DESC LIMIT 1",
            (f"violation-{check_name}", check_name),
        ).fetchone()
        assert failed == (0,)
    finally:
        connection.close()
        close_logger(logger)


def test_quarantine_file_matches_ledger_after_batch_reprocessing(tmp_path):
    config = load_config(ROOT / "config.yaml")
    raw = generate_data(ROOT / "config.yaml", tmp_path)
    entities = json.loads((tmp_path / "data" / "reference.json").read_text(encoding="utf-8"))

    for attempt in range(2):
        connection = connect(tmp_path / f"fresh_{attempt}.sqlite", ROOT / "sql" / "schema.sql")
        load_entities(connection, entities)
        logger = make_logger(tmp_path / "logs", f"quarantine-test-{attempt}")
        try:
            process_batch("batch_day1", raw / "batch_day1", config, entities, connection, logger, tmp_path)
            for source in ("scheduling", "claims", "support"):
                expected = connection.execute(
                    "SELECT rejected_count FROM processed_batches WHERE batch_id = ?",
                    (f"batch_day1:{source}",),
                ).fetchone()[0]
                quarantine_file = tmp_path / config["paths"]["quarantine"] / "batch_day1" / f"{source}.jsonl"
                actual = len(quarantine_file.read_text(encoding="utf-8").splitlines())
                assert actual == expected
        finally:
            connection.close()
            close_logger(logger)
