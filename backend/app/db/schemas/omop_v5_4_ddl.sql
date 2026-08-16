-- =============================================================================
-- VigilAI Phase 1 — OMOP CDM v5.4 core DDL (PostgreSQL)
-- =============================================================================
-- BIGINT primary / concept identifiers support RxNorm Extension / Athena-scale IDs
-- and prevent NumericValueOutOfRange against INTEGER (max 2_147_483_647).
--
-- drug_exposure and condition_occurrence are RANGE-partitioned by start date.
-- Yearly partitions cover 2000-01-01 .. 2031-01-01; a DEFAULT partition absorbs
-- out-of-range rows so inserts never fail for missing partitions.
--
-- Safe to re-run: objects are created with IF NOT EXISTS where supported.
-- Partition children use IF NOT EXISTS via DO blocks for PG 14+ compatibility.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. CONCEPT
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS concept (
    concept_id            BIGINT       NOT NULL,
    concept_name          VARCHAR(255) NOT NULL,
    domain_id             VARCHAR(20)  NOT NULL,
    vocabulary_id         VARCHAR(20)  NOT NULL,
    concept_class_id      VARCHAR(20)  NOT NULL,
    standard_concept      VARCHAR(1)   NULL,
    concept_code          VARCHAR(50)  NOT NULL,
    valid_start_date      DATE         NOT NULL,
    valid_end_date        DATE         NOT NULL,
    invalid_reason        VARCHAR(1)   NULL,
    CONSTRAINT xpk_concept PRIMARY KEY (concept_id)
);

CREATE INDEX IF NOT EXISTS idx_concept_concept_name
    ON concept (concept_name);
CREATE INDEX IF NOT EXISTS idx_concept_domain_id
    ON concept (domain_id);
CREATE INDEX IF NOT EXISTS idx_concept_vocabulary_id
    ON concept (vocabulary_id);
CREATE INDEX IF NOT EXISTS idx_concept_concept_code
    ON concept (concept_code);
CREATE INDEX IF NOT EXISTS idx_concept_std_class
    ON concept (standard_concept, concept_class_id);

-- ---------------------------------------------------------------------------
-- 2. PERSON
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS person (
    person_id                    BIGINT       NOT NULL,
    gender_concept_id            BIGINT       NOT NULL,
    year_of_birth                INTEGER      NULL,
    month_of_birth               INTEGER      NULL,
    day_of_birth                 INTEGER      NULL,
    birth_datetime               TIMESTAMP    NULL,
    race_concept_id              BIGINT       NOT NULL DEFAULT 0,
    ethnicity_concept_id         BIGINT       NOT NULL DEFAULT 0,
    location_id                  BIGINT       NULL,
    provider_id                  BIGINT       NULL,
    care_site_id                 BIGINT       NULL,
    person_source_value          VARCHAR(50)  NULL,
    gender_source_value          VARCHAR(50)  NULL,
    gender_source_concept_id     BIGINT       NULL,
    race_source_value            VARCHAR(50)  NULL,
    race_source_concept_id       BIGINT       NULL,
    ethnicity_source_value       VARCHAR(50)  NULL,
    ethnicity_source_concept_id  BIGINT       NULL,
    CONSTRAINT xpk_person PRIMARY KEY (person_id)
);

CREATE INDEX IF NOT EXISTS idx_person_gender_concept_id
    ON person (gender_concept_id);
CREATE INDEX IF NOT EXISTS idx_person_race_concept_id
    ON person (race_concept_id);
CREATE INDEX IF NOT EXISTS idx_person_ethnicity_concept_id
    ON person (ethnicity_concept_id);
CREATE INDEX IF NOT EXISTS idx_person_location_id
    ON person (location_id);
CREATE INDEX IF NOT EXISTS idx_person_person_source_value
    ON person (person_source_value);

-- ---------------------------------------------------------------------------
-- 3. DRUG_EXPOSURE (partitioned by drug_exposure_start_date)
-- PK must include the partition key (PostgreSQL requirement).
-- No FKs TO this table from parents; person_id / concept_id are logical only
-- so partitioning stays unconstrained by referencing FK rules.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS drug_exposure (
    drug_exposure_id              BIGINT         NOT NULL,
    person_id                     BIGINT         NOT NULL,
    drug_concept_id               BIGINT         NOT NULL,
    drug_exposure_start_date      DATE           NOT NULL,
    drug_exposure_start_datetime  TIMESTAMP      NULL,
    drug_exposure_end_date        DATE           NULL,
    drug_exposure_end_datetime    TIMESTAMP      NULL,
    verbatim_end_date             DATE           NULL,
    drug_type_concept_id          BIGINT         NOT NULL,
    stop_reason                   VARCHAR(20)    NULL,
    refills                       INTEGER        NULL,
    quantity                      NUMERIC        NULL,
    days_supply                   INTEGER        NULL,
    sig                           TEXT           NULL,
    route_concept_id              BIGINT         NULL,
    lot_number                    VARCHAR(50)    NULL,
    provider_id                   BIGINT         NULL,
    visit_occurrence_id           BIGINT         NULL,
    visit_detail_id               BIGINT         NULL,
    drug_source_value             VARCHAR(50)    NULL,
    drug_source_concept_id        BIGINT         NULL,
    route_source_value            VARCHAR(50)    NULL,
    dose_unit_source_value        VARCHAR(50)    NULL,
    CONSTRAINT xpk_drug_exposure
        PRIMARY KEY (drug_exposure_id, drug_exposure_start_date)
) PARTITION BY RANGE (drug_exposure_start_date);

CREATE INDEX IF NOT EXISTS idx_drug_exposure_person_id
    ON drug_exposure (person_id);
CREATE INDEX IF NOT EXISTS idx_drug_exposure_drug_concept_id
    ON drug_exposure (drug_concept_id);
CREATE INDEX IF NOT EXISTS idx_drug_exposure_start_date
    ON drug_exposure (drug_exposure_start_date);
CREATE INDEX IF NOT EXISTS idx_drug_exposure_person_drug
    ON drug_exposure (person_id, drug_concept_id);
CREATE INDEX IF NOT EXISTS idx_drug_exposure_type_concept_id
    ON drug_exposure (drug_type_concept_id);

-- Yearly partitions 2000 .. 2030 + DEFAULT catch-all
DO $$
DECLARE
    y INTEGER;
    part_name TEXT;
    from_d TEXT;
    to_d TEXT;
BEGIN
    FOR y IN 2000..2030 LOOP
        part_name := format('drug_exposure_y%s', y);
        from_d := format('%s-01-01', y);
        to_d := format('%s-01-01', y + 1);
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF drug_exposure
             FOR VALUES FROM (%L) TO (%L)',
            part_name, from_d, to_d
        );
    END LOOP;

    -- Out-of-range / NULL-adjacent safety net (NULL start_date cannot land here;
    -- start_date is NOT NULL — DEFAULT covers dates < 2000 or >= 2031)
    EXECUTE '
        CREATE TABLE IF NOT EXISTS drug_exposure_default
        PARTITION OF drug_exposure DEFAULT';
END $$;

-- ---------------------------------------------------------------------------
-- 4. CONDITION_OCCURRENCE (partitioned by condition_start_date)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS condition_occurrence (
    condition_occurrence_id          BIGINT        NOT NULL,
    person_id                        BIGINT        NOT NULL,
    condition_concept_id             BIGINT        NOT NULL,
    condition_start_date             DATE          NOT NULL,
    condition_start_datetime         TIMESTAMP     NULL,
    condition_end_date               DATE          NULL,
    condition_end_datetime           TIMESTAMP     NULL,
    condition_type_concept_id        BIGINT        NOT NULL,
    condition_status_concept_id      BIGINT        NULL,
    stop_reason                      VARCHAR(20)   NULL,
    provider_id                      BIGINT        NULL,
    visit_occurrence_id              BIGINT        NULL,
    visit_detail_id                  BIGINT        NULL,
    condition_source_value           VARCHAR(50)   NULL,
    condition_source_concept_id      BIGINT        NULL,
    condition_status_source_value    VARCHAR(50)   NULL,
    CONSTRAINT xpk_condition_occurrence
        PRIMARY KEY (condition_occurrence_id, condition_start_date)
) PARTITION BY RANGE (condition_start_date);

CREATE INDEX IF NOT EXISTS idx_condition_occurrence_person_id
    ON condition_occurrence (person_id);
CREATE INDEX IF NOT EXISTS idx_condition_occurrence_concept_id
    ON condition_occurrence (condition_concept_id);
CREATE INDEX IF NOT EXISTS idx_condition_occurrence_start_date
    ON condition_occurrence (condition_start_date);
CREATE INDEX IF NOT EXISTS idx_condition_occurrence_person_condition
    ON condition_occurrence (person_id, condition_concept_id);
CREATE INDEX IF NOT EXISTS idx_condition_occurrence_type_concept_id
    ON condition_occurrence (condition_type_concept_id);

DO $$
DECLARE
    y INTEGER;
    part_name TEXT;
    from_d TEXT;
    to_d TEXT;
BEGIN
    FOR y IN 2000..2030 LOOP
        part_name := format('condition_occurrence_y%s', y);
        from_d := format('%s-01-01', y);
        to_d := format('%s-01-01', y + 1);
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF condition_occurrence
             FOR VALUES FROM (%L) TO (%L)',
            part_name, from_d, to_d
        );
    END LOOP;

    EXECUTE '
        CREATE TABLE IF NOT EXISTS condition_occurrence_default
        PARTITION OF condition_occurrence DEFAULT';
END $$;
