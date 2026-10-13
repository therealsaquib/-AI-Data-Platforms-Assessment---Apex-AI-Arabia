import json
import json
from pathlib import Path

import pytest

from src.generate_data import generate_data
from src.ingest import SchemaDriftError, canonicalize_headers, load_config, read_records
from src.load import connect, load_entities, load_rows
from src.logger import close_logger, make_logger
from src.pipeline import process_batch
from src.transform import normalize_status, parse_timestamp


ROOT = Path(__file__).resolve().parents[1]


def test_status_normalization_handles_case_variants():
    assert normalize_status("CANCELED", {"canceled": "cancelled"}) == "cancelled"


def test_timestamp_parser_returns_utc_iso_and_rejects_invalid():
    assert parse_timestamp("2026-09-01T00:00:00-04:00") == "2026-09-01T04:00:00+00:00"
    assert parse_timestamp("not a date") is None


def test_config_loads_expected_sections():
    config = load_config(ROOT / "config.yaml")
    assert {"paths", "columns", "statuses", "thresholds"} <= config.keys()


def test_known_renamed_column_maps_and_unknown_column_fails():
    config = load_config(ROOT / "config.yaml")
    assert canonicalize_headers([{"scheduled_at": "2026-09-01"}], "scheduling", config)[0]["appointment_time"] == "2026-09-01"
    with pytest.raises(SchemaDriftError, match="config.yaml"):
        canonicalize_headers([{"appointment_time_new_unknown": "2026-09-01"}], "scheduling", config)


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
