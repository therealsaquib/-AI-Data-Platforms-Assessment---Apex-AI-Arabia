"""Transparent SQL checks; every outcome is persisted, including failures."""

from typing import Any


class DQFailureError(RuntimeError):
    """Raised when a hard data-quality check fails."""


def run_quality_checks(connection: Any, logger: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    checks = [
        ("appointments_unique", "SELECT COUNT(*) = COUNT(DISTINCT appointment_id) FROM fact_appointment", "business-key uniqueness"),
        ("claims_unique", "SELECT COUNT(*) = COUNT(DISTINCT claim_id) FROM fact_claim", "business-key uniqueness"),
        ("support_unique", "SELECT COUNT(*) = COUNT(DISTINCT interaction_id) FROM fact_support_interaction", "business-key uniqueness"),
        ("facts_not_null", "SELECT COUNT(*) = 0 FROM (SELECT appointment_id AS k FROM fact_appointment WHERE appointment_id IS NULL UNION ALL SELECT claim_id FROM fact_claim WHERE claim_id IS NULL UNION ALL SELECT interaction_id FROM fact_support_interaction WHERE interaction_id IS NULL)", "non-null fact business keys"),
        ("patient_references", "SELECT COUNT(*) = 0 FROM (SELECT patient_id FROM fact_appointment UNION ALL SELECT patient_id FROM fact_claim UNION ALL SELECT patient_id FROM fact_support_interaction) f LEFT JOIN dim_patient d USING (patient_id) WHERE d.patient_id IS NULL", "patient referential integrity"),
        ("provider_references", "SELECT COUNT(*) = 0 FROM (SELECT provider_id FROM fact_appointment UNION ALL SELECT provider_id FROM fact_claim UNION ALL SELECT provider_id FROM fact_support_interaction) f LEFT JOIN dim_provider d USING (provider_id) WHERE d.provider_id IS NULL", "provider referential integrity"),
        ("date_references", "SELECT COUNT(*) = 0 FROM fact_appointment f LEFT JOIN dim_date d ON f.event_date = d.date_key WHERE d.date_key IS NULL UNION ALL SELECT COUNT(*) = 0 FROM fact_support_interaction f LEFT JOIN dim_date d ON f.opened_date = d.date_key WHERE d.date_key IS NULL", "date dimension referential integrity"),
        ("duplicate_detection", "SELECT COUNT(*) > 0 FROM (SELECT source, business_key FROM fact_record_history GROUP BY source, business_key HAVING COUNT(*) > 1)", "repeated business keys are detected in accepted history"),
        ("history_completeness", "SELECT (SELECT COUNT(*) FROM fact_record_history) = COALESCE((SELECT SUM(staged_count) FROM processed_batches WHERE status='success'), 0)", "every staged accepted row has a corresponding history record"),
    ]
    expected_text_columns = {
        "fact_appointment": {"appointment_id", "patient_id", "provider_id", "appointment_at", "status"},
        "fact_claim": {"claim_id", "patient_id", "provider_id", "status"},
        "fact_support_interaction": {"interaction_id", "patient_id", "provider_id", "opened_at", "status"},
    }
    actual_types: dict[str, dict[str, str]] = {}
    for table, expected_columns in expected_text_columns.items():
        actual_types[table] = {
            column[1]: column[2].upper()
            for column in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
    schema_passed = all(
        actual_types[table].get(column) == "TEXT"
        for table, columns in expected_text_columns.items()
        for column in columns
    )
    results: list[dict[str, Any]] = []
    for name, sql, description in checks:
        # UNION returns multiple booleans for a few compound SQL expressions, so inspect all.
        values = connection.execute(sql).fetchall()
        passed = bool(values) and all(bool(value[0]) for value in values)
        results.append({"check_name": name, "passed": passed, "details": description})
    statuses = config["statuses"]
    status_sql = (
        "SELECT COUNT(*) = 0 FROM fact_appointment WHERE status NOT IN "
        f"({','.join('?' for _ in set(statuses['appointment'].values()))}) UNION ALL "
        "SELECT COUNT(*) = 0 FROM fact_claim WHERE status NOT IN "
        f"({','.join('?' for _ in set(statuses['claim'].values()))}) UNION ALL "
        "SELECT COUNT(*) = 0 FROM fact_support_interaction WHERE status NOT IN "
        f"({','.join('?' for _ in set(statuses['support'].values()))})"
    )
    status_params = tuple(
        value for source in ("appointment", "claim", "support")
        for value in sorted(set(statuses[source].values()))
    )
    status_outcomes = connection.execute(status_sql, status_params).fetchall()
    results.append({
        "check_name": "accepted_statuses",
        "passed": bool(status_outcomes) and all(bool(row[0]) for row in status_outcomes),
        "details": "normalized statuses must be present in the configured mapping values",
    })
    thresholds = config["thresholds"]
    minimum_timestamp = thresholds["minimum_timestamp"]
    maximum_timestamp = thresholds["maximum_timestamp"]
    timestamp_outcomes = connection.execute(
        "SELECT COUNT(*) = 0 FROM fact_appointment WHERE appointment_at < ? OR appointment_at > ? "
        "UNION ALL SELECT COUNT(*) = 0 FROM fact_support_interaction WHERE opened_at < ? OR opened_at > ?",
        (minimum_timestamp, maximum_timestamp, minimum_timestamp, maximum_timestamp),
    ).fetchall()
    results.append({
        "check_name": "timestamp_range",
        "passed": bool(timestamp_outcomes) and all(bool(row[0]) for row in timestamp_outcomes),
        "details": f"event timestamps are within {minimum_timestamp} and {maximum_timestamp}",
    })
    amount_outcome = connection.execute(
        "SELECT COUNT(*) = 0 FROM fact_claim WHERE amount < 0 OR amount > ?",
        (thresholds["maximum_claim_amount"],),
    ).fetchone()
    results.append({
        "check_name": "claim_amounts",
        "passed": bool(amount_outcome[0]),
        "details": f"claim amounts are nonnegative and at most {thresholds['maximum_claim_amount']}",
    })
    count_queries = {
        "scheduling": "SELECT COUNT(*) FROM fact_appointment",
        "claims": "SELECT COUNT(*) FROM fact_claim",
        "support": "SELECT COUNT(*) FROM fact_support_interaction",
    }
    for source, query in count_queries.items():
        count = int(connection.execute(query).fetchone()[0])
        minimum_rows = thresholds["minimum_rows"]
        passed = count >= minimum_rows[source]
        results.append({
            "check_name": f"{source}_minimum_row_count",
            "passed": passed,
            "details": f"curated_count={count}; expected_at_least={minimum_rows[source]}",
        })
    results.append({
        "check_name": "schema_and_type_validation",
        "passed": schema_passed,
        "details": "required fact key, timestamp, and status columns must exist with SQLite TEXT type",
    })
    for result in results:
        connection.execute(
            "INSERT INTO dq_results (check_name, passed, details, checked_at) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            (result["check_name"], int(result["passed"]), result["details"]),
        )
        logger.info(
            "stage=dq check=%s status=%s details=%s",
            result["check_name"], "PASS" if result["passed"] else "FAIL", result["details"],
        )
    connection.commit()
    failed = [result for result in results if not result["passed"]]
    if failed:
        names = ", ".join(result["check_name"] for result in failed)
        raise DQFailureError(f"{len(failed)} data-quality check(s) failed: {names}")
    return results
