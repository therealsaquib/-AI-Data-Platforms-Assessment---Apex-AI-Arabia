"""Validate source rows, standardize values, and quarantine every rejected row."""

from typing import Any

import pandas as pd


def parse_timestamp(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    parsed = pd.to_datetime(value, utc=True, errors="coerce", format="mixed")
    if pd.isna(parsed):
        return None
    return parsed.isoformat()


def normalize_status(value: Any, mapping: dict[str, str]) -> str | None:
    if value is None:
        return None
    return mapping.get(str(value).strip().lower())


def transform_rows(
    records: list[dict[str, Any]],
    source: str,
    config: dict[str, Any],
    entities: dict[str, list[str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    id_field = {
        "scheduling": "appointment_id",
        "claims": "claim_id",
        "support": "interaction_id",
    }[source]
    time_fields = {
        "scheduling": ["appointment_time", "updated_at"],
        "claims": ["updated_at"],
        "support": ["opened_at", "closed_at", "updated_at"],
    }[source]
    lower = pd.Timestamp(config["thresholds"]["minimum_timestamp"])
    upper = pd.Timestamp(config["thresholds"]["maximum_timestamp"])
    entity_ids = {
        "patient_id": set(entities["patients"]),
        "provider_id": set(entities["providers"]),
    }
    for line_number, original in enumerate(records, start=2):
        row = dict(original)
        reasons: list[str] = []
        for field in [id_field, "patient_id", "provider_id"]:
            if not row.get(field) or not str(row[field]).strip():
                reasons.append(f"missing_{field}")
        for field in ("patient_id", "provider_id"):
            if row.get(field) and str(row[field]) not in entity_ids[field]:
                reasons.append(f"orphan_{field}")
        for field in time_fields:
            parsed = parse_timestamp(row.get(field))
            if parsed is None:
                reasons.append(f"invalid_{field}")
            else:
                timestamp = pd.Timestamp(parsed)
                if timestamp < lower or timestamp > upper:
                    reasons.append(f"out_of_range_{field}")
                row[field] = parsed
        row["status"] = normalize_status(
            row.get("status"), config["statuses"][{
                "scheduling": "appointment",
                "claims": "claim",
                "support": "support",
            }[source]]
        )
        if row["status"] is None:
            reasons.append("unrecognized_status")
        if source == "claims":
            try:
                row["amount"] = float(row.get("amount"))
            except (TypeError, ValueError):
                row["amount"] = None
            if row["amount"] is None:
                reasons.append("invalid_amount")
            elif row["amount"] < 0 or row["amount"] > config["thresholds"]["maximum_claim_amount"]:
                reasons.append("amount_out_of_range")
        if source == "support" and row.get("closed_at"):
            if row.get("opened_at") and row["closed_at"] < row["opened_at"]:
                reasons.append("closed_before_opened")
        row["source_row_number"] = line_number
        if reasons:
            row["reject_reason"] = ";".join(sorted(set(reasons)))
            rejected.append(row)
        else:
            row["reject_reason"] = ""
            valid.append(row)
    return valid, rejected
