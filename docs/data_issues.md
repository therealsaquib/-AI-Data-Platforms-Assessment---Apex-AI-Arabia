# Synthetic issue map

All inputs are generated locally by `src/generate_data.py` using Faker and a
fixed seed. There are no real patient records or external datasets.

| Issue | Where planted |
|---|---|
| Duplicate source records | Scheduling row 13, claims row 5, support row 4 in day one |
| Inconsistent source column names | Claims uses `patient`, `provider`, `appointment_ref`, `claim_amount`; support uses `ticket_id` and `resolution_status` |
| Null IDs | Scheduling row 19 patient ID, claims row 30 claim ID, support row 20 patient ID |
| Null dates | Scheduling row 26 appointment time, support row 24 close time |
| Invalid timestamps | Scheduling row 8, claims row 36, support row 10 |
| Mixed date formats | Scheduling row 41 and support row 34 use US-style month/day dates |
| Status spellings/case differences | Scheduling rows use `Cancelled`, `canceled`, and `CANCELED` plus other case variants |
| Negative/outlier amounts | Claims rows 11 and 18 |
| Orphan foreign keys | Scheduling row 32 provider; claims row 22 patient; support row 28 provider |
| Late-arriving record | Day-two appointment `APT00999` dated October 11 |
| Corrected record | Day two updates `APT00001` to `Rescheduled` with a newer `updated_at` |
| Duplicate redelivery | Day two repeats day-one rows in all three sources |
| Renamed column | Day-two scheduling uses `scheduled_at`; config maps this known alias |
| New status value | Day-two `Rescheduled`; the configured normalization map accepts it |

Rows that cannot be parsed or validated are placed in quarantine, not dropped.
