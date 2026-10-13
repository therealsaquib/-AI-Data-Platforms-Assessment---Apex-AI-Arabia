"""SQLite schema creation and deterministic current-state upserts with row history."""

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


def connect(database: Path, schema_path: Path) -> sqlite3.Connection:
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(schema_path.read_text(encoding="utf-8"))
    return connection


def _date_dimension(connection: sqlite3.Connection, timestamp: str) -> str:
    day = datetime.fromisoformat(timestamp).date()
    key = day.isoformat()
    connection.execute(
        "INSERT OR IGNORE INTO dim_date VALUES (?, ?, ?, ?, ?)",
        (key, day.year, day.month, day.day, day.weekday()),
    )
    return key


def _insert_history(
    connection: sqlite3.Connection, source: str, key: str, row: dict[str, Any],
    batch_id: str,
) -> int:
    updated = row["updated_at"]
    existing = connection.execute(
        "SELECT COALESCE(MAX(record_version), 0) FROM fact_record_history "
        "WHERE source = ? AND business_key = ?",
        (source, key),
    ).fetchone()[0]
    version = int(existing) + 1
    payload = json.dumps(row, sort_keys=True, separators=(",", ":"))
    history_id = hashlib.sha256(
        f"{batch_id}|{source}|{key}|{row['source_row_number']}|{payload}".encode()
    ).hexdigest()
    connection.execute(
        "INSERT OR IGNORE INTO fact_record_history "
        "(history_id, source, business_key, record_version, updated_at, batch_id, row_number, payload) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (history_id, source, key, version, updated, batch_id, row["source_row_number"], payload),
    )
    return version


def _upsert(connection: sqlite3.Connection, table: str, key_name: str, row: dict[str, Any], batch_id: str) -> None:
    key = str(row[key_name])
    source = {"fact_appointment": "scheduling", "fact_claim": "claims", "fact_support_interaction": "support"}[table]
    version = _insert_history(connection, source, key, row, batch_id)
    current = connection.execute(
        f"SELECT updated_at FROM {table} WHERE {key_name} = ?", (key,)
    ).fetchone()
    if current and current[0] > row["updated_at"]:
        return
    if table == "fact_appointment":
        columns = ("appointment_id", "patient_id", "provider_id", "appointment_at", "event_date", "status", "updated_at", "record_version")
        values = (key, row["patient_id"], row["provider_id"], row["appointment_time"], _date_dimension(connection, row["appointment_time"]), row["status"], row["updated_at"], version)
    elif table == "fact_claim":
        columns = ("claim_id", "patient_id", "provider_id", "appointment_id", "amount", "status", "updated_at", "record_version")
        values = (key, row["patient_id"], row["provider_id"], row.get("appointment_id"), row["amount"], row["status"], row["updated_at"], version)
    else:
        columns = ("interaction_id", "patient_id", "provider_id", "opened_at", "opened_date", "closed_at", "status", "updated_at", "record_version")
        values = (key, row["patient_id"], row["provider_id"], row["opened_at"], _date_dimension(connection, row["opened_at"]), row.get("closed_at") or None, row["status"], row["updated_at"], version)
    assignments = ", ".join(f"{column}=excluded.{column}" for column in columns if column != key_name)
    connection.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)}) "
        f"ON CONFLICT({key_name}) DO UPDATE SET {assignments}",
        values,
    )


def load_entities(connection: sqlite3.Connection, entities: dict[str, list[str]]) -> None:
    connection.executemany(
        "INSERT OR IGNORE INTO dim_patient VALUES (?, ?)",
        [(item, item) for item in entities["patients"]],
    )
    connection.executemany(
        "INSERT OR IGNORE INTO dim_provider VALUES (?, ?)",
        [(item, item) for item in entities["providers"]],
    )
    connection.commit()


def load_rows(
    connection: sqlite3.Connection,
    source: str,
    rows: list[dict[str, Any]],
    batch_id: str,
) -> None:
    table, key = {
        "scheduling": ("fact_appointment", "appointment_id"),
        "claims": ("fact_claim", "claim_id"),
        "support": ("fact_support_interaction", "interaction_id"),
    }[source]
    for row in rows:
        _upsert(connection, table, key, row, batch_id)
    connection.commit()
