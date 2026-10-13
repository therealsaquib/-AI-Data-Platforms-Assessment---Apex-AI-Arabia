-- 1. Appointment detail joined to patient/provider/date dimensions.
SELECT a.appointment_id, a.status, a.appointment_at, p.patient_key, v.provider_key, d.year, d.month
FROM fact_appointment a
JOIN dim_patient p USING (patient_id)
JOIN dim_provider v USING (provider_id)
JOIN dim_date d ON a.event_date = d.date_key
ORDER BY a.appointment_at;

-- 2. Appointment counts by normalized status.
SELECT status, COUNT(*) AS appointment_count
FROM fact_appointment
GROUP BY status
ORDER BY appointment_count DESC;

-- 3. Claim approval rate (approved includes the source's "paid" alias).
SELECT COUNT(*) AS total_claims,
       SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) AS approved_claims,
       ROUND(100.0 * SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS approval_rate_pct
FROM fact_claim;

-- 4. Average resolved support time in hours.
SELECT ROUND(AVG((julianday(closed_at) - julianday(opened_at)) * 24), 2) AS avg_resolution_hours
FROM fact_support_interaction
WHERE status = 'resolved' AND closed_at IS NOT NULL;

-- 5. Duplicates observed in full row history by business key.
SELECT source, business_key, COUNT(*) AS observed_versions
FROM fact_record_history
GROUP BY source, business_key
HAVING COUNT(*) > 1
ORDER BY observed_versions DESC;

-- 6. Latest data-quality results.
SELECT check_name, passed, details, checked_at
FROM dq_results
WHERE checked_at = (SELECT MAX(checked_at) FROM dq_results)
ORDER BY check_name;

-- 7. KPI lower than source: reconcile raw, accepted/staged, current curated, quarantined.
-- Current facts can be smaller because repeated business keys are deliberately upserted.
WITH batch_counts(source, raw_count, staged_count, quarantine_count) AS (
    SELECT 'scheduling', SUM(row_count), SUM(staged_count), SUM(rejected_count)
      FROM processed_batches WHERE batch_id LIKE '%:scheduling'
    UNION ALL SELECT 'claims', SUM(row_count), SUM(staged_count), SUM(rejected_count)
      FROM processed_batches WHERE batch_id LIKE '%:claims'
    UNION ALL SELECT 'support', SUM(row_count), SUM(staged_count), SUM(rejected_count)
      FROM processed_batches WHERE batch_id LIKE '%:support'
),
curated(source, curated_count) AS (
    SELECT 'scheduling', COUNT(*) FROM fact_appointment
    UNION ALL SELECT 'claims', COUNT(*) FROM fact_claim
    UNION ALL SELECT 'support', COUNT(*) FROM fact_support_interaction
)
SELECT b.source, b.raw_count, b.staged_count, c.curated_count, b.quarantine_count,
       b.raw_count - b.staged_count - b.quarantine_count AS unexplained_rows
FROM batch_counts b
JOIN curated c USING(source)
ORDER BY b.source;
