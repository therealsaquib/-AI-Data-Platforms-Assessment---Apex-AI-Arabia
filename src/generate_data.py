"""Create reproducible, entirely synthetic source data with deliberate defects."""

import csv
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
from faker import Faker

from src.ingest import load_config


def _iso(value: datetime) -> str:
    return value.isoformat()


def _day_one(seed: int) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    fake = Faker()
    fake.seed_instance(seed)
    rng = random.Random(seed)
    patients = [f"PAT{i:04d}" for i in range(1, 181)]
    providers = [f"PRV{i:03d}" for i in range(1, 21)]
    base = datetime(2026, 9, 1, tzinfo=timezone.utc)
    schedules: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    support: list[dict[str, Any]] = []
    statuses = ["Scheduled", "confirmed", "CANCELED", "Cancelled", "no-show", "Completed"]
    for i in range(320):
        start = base + timedelta(minutes=fake.random_int(0, 60 * 24 * 45))
        appointment_id = f"APT{i + 1:05d}"
        schedules.append({
            "appointment_id": appointment_id,
            "patient_id": rng.choice(patients),
            "provider_id": rng.choice(providers),
            "appointment_time": _iso(start),
            "status": rng.choice(statuses),
            "updated_at": _iso(start + timedelta(hours=rng.randint(0, 72))),
        })
    # Keep a repeated business key as evidence; loading records history preserves both rows.
    schedules.append(dict(schedules[12]))
    schedules[7]["appointment_time"] = "not-a-timestamp"
    schedules[18]["patient_id"] = ""
    schedules[25]["appointment_time"] = ""
    schedules[31]["provider_id"] = "PRV999"
    schedules[40]["appointment_time"] = base.strftime("%m/%d/%Y %H:%M")

    for i in range(260):
        updated = base + timedelta(minutes=fake.random_int(0, 60 * 24 * 45))
        claims.append({
            "claim_id": f"CLM{i + 1:05d}",
            "patient": rng.choice(patients),
            "provider": rng.choice(providers),
            "appointment_ref": f"APT{rng.randint(1, 320):05d}",
            "claim_amount": round(rng.uniform(25, 4500), 2),
            "claim_status": rng.choice(["Submitted", "Approved", "pending", "Denied"]),
            "updated_at": _iso(updated),
        })
    claims.append(dict(claims[4]))
    claims[10]["claim_amount"] = -42.5
    claims[17]["claim_amount"] = 90000
    claims[21]["patient"] = "PAT9999"
    claims[29]["claim_id"] = ""
    claims[35]["updated_at"] = "32/13/2026"

    for i in range(300):
        opened = base + timedelta(minutes=rng.randint(0, 60 * 24 * 45))
        closed = opened + timedelta(hours=rng.randint(1, 96))
        support.append({
            "ticket_id": f"TKT{i + 1:05d}",
            "patient_id": rng.choice(patients),
            "provider_id": rng.choice(providers),
            "opened_at": _iso(opened),
            "closed_at": _iso(closed),
            "resolution_status": rng.choice(["Open", "Closed", "resolved", "In Progress"]),
            "updated_at": _iso(closed),
        })
    support.append(dict(support[3]))
    support[9]["opened_at"] = "bad timestamp"
    support[19]["patient_id"] = ""
    support[23]["closed_at"] = ""
    support[27]["provider_id"] = "PRV998"
    support[33]["opened_at"] = base.strftime("%m/%d/%Y %H:%M")
    return {
        "scheduling": schedules,
        "claims": claims,
        "support": support,
    }, {"patients": patients, "providers": providers}


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def generate_data(config_path: Path, output_root: Path | None = None) -> Path:
    config = load_config(config_path)
    root = output_root or config_path.parent
    batches = root / config["paths"]["raw"]
    day1, entities = _day_one(int(config["seed"]))
    first = batches / "batch_day1"
    second = batches / "batch_day2"
    _write_csv(first / "scheduling.csv", day1["scheduling"])
    (first / "claims.json").write_text(
        json.dumps(day1["claims"], indent=2), encoding="utf-8"
    )
    _write_csv(first / "support.csv", day1["support"])

    # Day two intentionally repeats delivered rows but also carries new versions.
    schedule2 = [dict(row) for row in day1["scheduling"][:24]]
    # A renamed source field is present consistently across this delivered file.
    for row in schedule2:
        row["scheduled_at"] = row.pop("appointment_time")
    schedule2[0]["status"] = "Rescheduled"
    schedule2[0]["updated_at"] = _iso(datetime(2026, 12, 5, tzinfo=timezone.utc))
    late = dict(day1["scheduling"][40])
    late.update(appointment_id="APT00999", appointment_time="2026-10-11T09:30:00+00:00")
    late["updated_at"] = "2026-10-11T10:00:00+00:00"
    late["scheduled_at"] = late.pop("appointment_time")
    schedule2.append(late)
    _write_csv(second / "scheduling.csv", schedule2)

    claims2 = [dict(row) for row in day1["claims"][:15]]
    claims2.append({
        "claim_id": "CLM00999", "patient": entities["patients"][3],
        "provider": entities["providers"][2], "appointment_ref": "APT00999",
        "claim_amount": 275.00, "claim_status": "approved",
        "updated_at": "2026-10-11T11:00:00+00:00",
    })
    (second / "claims.json").write_text(json.dumps(claims2, indent=2), encoding="utf-8")
    support2 = [dict(row) for row in day1["support"][:12]]
    _write_csv(second / "support.csv", support2)
    (root / "data" / "reference.json").write_text(
        json.dumps(entities, indent=2), encoding="utf-8"
    )
    return batches


if __name__ == "__main__":
    print(generate_data(Path(__file__).resolve().parents[1] / "config.yaml"))
