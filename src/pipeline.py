"""Command-line runner for day-one/day-two processing and controlled demos."""

import argparse
import csv
import hashlib
import json
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from src.generate_data import generate_data
from src.ingest import (
    SchemaDriftError,
    canonicalize_headers,
    load_config,
    read_records,
)
from src.load import connect, load_entities, load_rows
from src.logger import close_logger, make_logger
from src.quality_checks import DQFailureError, run_quality_checks
from src.transform import transform_rows


ROOT = Path(__file__).resolve().parents[1]
SOURCES = {"scheduling": "scheduling.csv", "claims": "claims.json", "support": "support.csv"}


def _write_staging(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_quarantine(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")


def process_batch(
    batch_id: str,
    batch_dir: Path,
    config: dict[str, Any],
    entities: dict[str, list[str]],
    connection: Any,
    logger: Any,
    root: Path,
) -> None:
    for source, filename in SOURCES.items():
        path = batch_dir / filename
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        file_batch_id = f"{batch_id}:{source}"
        done = connection.execute(
            "SELECT file_hash, status FROM processed_batches WHERE batch_id = ?",
            (file_batch_id,),
        ).fetchone()
        if done and done[0] == digest and done[1] == "success":
            logger.info("stage=ingest batch=%s source=%s status=SKIP unchanged hash=%s", batch_id, source, digest[:12])
            continue
        if done:
            raise ValueError(
                f"Batch {file_batch_id} was already processed with a different file hash; "
                "deliver changed contents under a new batch ID so prior quarantine and audit counts remain traceable."
            )
        started = time.perf_counter()
        raw = read_records(path, source)
        canonical = canonicalize_headers(raw, source, config)
        valid, rejected = transform_rows(canonical, source, config, entities)
        staging_file = root / config["paths"]["staging"] / batch_id / f"{source}.csv"
        quarantine_file = root / config["paths"]["quarantine"] / batch_id / f"{source}.jsonl"
        staging_file.parent.mkdir(parents=True, exist_ok=True)
        _write_staging(staging_file, valid)
        _write_quarantine(quarantine_file, rejected)
        load_rows(connection, source, valid, batch_id)
        connection.execute(
            "INSERT INTO processed_batches "
            "(batch_id, file_hash, row_count, staged_count, rejected_count, status) "
            "VALUES (?, ?, ?, ?, ?, 'success') ON CONFLICT(batch_id) DO UPDATE SET "
            "file_hash=excluded.file_hash, row_count=excluded.row_count, "
            "staged_count=excluded.staged_count, rejected_count=excluded.rejected_count, status='success', "
            "processed_at=CURRENT_TIMESTAMP",
            (file_batch_id, digest, len(raw), len(valid), len(rejected)),
        )
        connection.commit()
        elapsed = time.perf_counter() - started
        logger.info(
            "stage=process batch=%s source=%s rows_in=%d staged=%d rejected=%d duration_seconds=%.3f",
            batch_id, source, len(raw), len(valid), len(rejected), elapsed,
        )


def _counts(connection: Any) -> dict[str, int]:
    tables = {
        "appointments": "fact_appointment",
        "claims": "fact_claim",
        "support": "fact_support_interaction",
    }
    return {name: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for name, table in tables.items()}


def _run_pipeline() -> None:
    config_path = ROOT / "config.yaml"
    config = load_config(config_path)
    root = ROOT
    raw_root = generate_data(config_path, root)
    run_id = str(uuid.uuid4())[:8]
    logger = make_logger(root / config["paths"]["logs"], run_id)
    entities = json.loads((root / "data" / "reference.json").read_text(encoding="utf-8"))
    connection = connect(root / config["paths"]["database"], ROOT / "sql" / "schema.sql")
    load_entities(connection, entities)
    try:
        for batch_name in ("batch_day1", "batch_day2"):
            process_batch(batch_name, raw_root / batch_name, config, entities, connection, logger, root)
        before_repeat = _counts(connection)
        process_batch("batch_day2", raw_root / "batch_day2", config, entities, connection, logger, root)
        after_repeat = _counts(connection)
        logger.info("stage=idempotency counts_before=%s counts_after=%s unchanged=%s", before_repeat, after_repeat, before_repeat == after_repeat)
        run_quality_checks(connection, logger, config)
        logger.info("stage=complete curated_counts=%s dq_status=PASS", _counts(connection))
        print(f"RUN_OK curated_counts={_counts(connection)} day2_repeat_unchanged={before_repeat == after_repeat}")
    finally:
        connection.close()


def schema_drift_demo() -> None:
    config = load_config(ROOT / "config.yaml")
    generate_data(ROOT / "config.yaml", ROOT)
    source_path = ROOT / config["paths"]["raw"] / "batch_day1" / "scheduling.csv"
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder) / "unknown_schema.csv"
        rows = read_records(source_path, "scheduling")
        for row in rows:
            row["appointment_time_new_unknown"] = row.pop("appointment_time")
        _write_staging(copy, rows)
        try:
            canonicalize_headers(read_records(copy, "scheduling"), "scheduling", config)
        except SchemaDriftError as error:
            print(f"EXPECTED CONTROLLED FAILURE: {error}")
            return
    raise RuntimeError("Schema-drift demo unexpectedly passed")


def dq_failure_demo() -> None:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        config = load_config(ROOT / "config.yaml")
        config["paths"]["database"] = "failure.db"
        config["paths"]["logs"] = "logs"
        # Run in an isolated temporary tree, so the demo cannot pollute user results.
        raw = generate_data(ROOT / "config.yaml", root)
        entities = json.loads((root / "data" / "reference.json").read_text(encoding="utf-8"))
        logger = make_logger(root / "logs", "dq-demo")
        connection = connect(root / "failure.db", ROOT / "sql" / "schema.sql")
        try:
            load_entities(connection, entities)
            for batch in ("batch_day1", "batch_day2"):
                process_batch(batch, raw / batch, config, entities, connection, logger, root)
            connection.execute(
                "UPDATE fact_appointment SET status='unexpected_status' "
                "WHERE appointment_id=(SELECT appointment_id FROM fact_appointment LIMIT 1)"
            )
            connection.commit()
            run_quality_checks(connection, logger, config)
        except DQFailureError as error:
            print(f"EXPECTED CONTROLLED FAILURE: {error}")
        else:
            raise RuntimeError("DQ failure demo unexpectedly passed")
        finally:
            connection.close()
            close_logger(logger)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    demos = parser.add_mutually_exclusive_group()
    demos.add_argument("--fail-demo", action="store_true", help="Run pipeline with one invalid curated status.")
    demos.add_argument("--schema-drift-demo", action="store_true", help="Show unknown source column failure.")
    args = parser.parse_args()
    if args.schema_drift_demo:
        schema_drift_demo()
    elif args.fail_demo:
        dq_failure_demo()
    else:
        _run_pipeline()


if __name__ == "__main__":
    main()
