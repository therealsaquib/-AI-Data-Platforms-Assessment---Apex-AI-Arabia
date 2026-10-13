# Star model

```mermaid
erDiagram
    DIM_PATIENT ||--o{ FACT_APPOINTMENT : patient_id
    DIM_PROVIDER ||--o{ FACT_APPOINTMENT : provider_id
    DIM_DATE ||--o{ FACT_APPOINTMENT : event_date
    DIM_PATIENT ||--o{ FACT_CLAIM : patient_id
    DIM_PROVIDER ||--o{ FACT_CLAIM : provider_id
    DIM_PATIENT ||--o{ FACT_SUPPORT_INTERACTION : patient_id
    DIM_PROVIDER ||--o{ FACT_SUPPORT_INTERACTION : provider_id
    DIM_DATE ||--o{ FACT_SUPPORT_INTERACTION : opened_date
    DIM_PATIENT { string patient_id PK string patient_key UK }
    DIM_PROVIDER { string provider_id PK string provider_key UK }
    DIM_DATE { string date_key PK int year int month int day int weekday }
    FACT_APPOINTMENT { string appointment_id PK string patient_id FK string provider_id FK string event_date FK string status int record_version }
    FACT_CLAIM { string claim_id PK string patient_id FK string provider_id FK string appointment_id string status float amount int record_version }
    FACT_SUPPORT_INTERACTION { string interaction_id PK string patient_id FK string provider_id FK string opened_date FK string status int record_version }
```

The three facts describe separate business processes and therefore retain their
own grains: one appointment, one claim, and one support interaction per row.
Shared pseudonymous patient/provider dimensions allow consistent cross-process
dashboards without inventing a combined fact grain. A date dimension makes time
grouping explicit. `fact_record_history` is an operational audit table rather
than a dashboard fact; it preserves every accepted source version.
