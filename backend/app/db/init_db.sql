-- VigilAI OMOP CDM v5.4 staging — PostgreSQL bootstrap / patch.
-- Ensures concept_id columns are BIGINT so RxNorm Extension / Athena-style
-- identifiers (and VigilAI surrogate hashes in the 2e9 range) do not raise
-- psycopg2.errors.NumericValueOutOfRange against INTEGER (max 2_147_483_647).
--
-- Safe to re-run. Application migrate_schema() also applies these ALTERs.

-- CONCEPT PK
ALTER TABLE IF EXISTS omop_concept
  ALTER COLUMN concept_id TYPE BIGINT;

-- PERSON gender / race / ethnicity concept FKs (CDM ints; widen for consistency)
ALTER TABLE IF EXISTS omop_person
  ALTER COLUMN gender_concept_id TYPE BIGINT;
ALTER TABLE IF EXISTS omop_person
  ALTER COLUMN race_concept_id TYPE BIGINT;
ALTER TABLE IF EXISTS omop_person
  ALTER COLUMN ethnicity_concept_id TYPE BIGINT;
ALTER TABLE IF EXISTS omop_person
  ALTER COLUMN gender_source_concept_id TYPE BIGINT;
ALTER TABLE IF EXISTS omop_person
  ALTER COLUMN race_source_concept_id TYPE BIGINT;
ALTER TABLE IF EXISTS omop_person
  ALTER COLUMN ethnicity_source_concept_id TYPE BIGINT;

-- DRUG_EXPOSURE concept FKs
ALTER TABLE IF EXISTS omop_drug_exposure
  ALTER COLUMN drug_concept_id_int TYPE BIGINT;
ALTER TABLE IF EXISTS omop_drug_exposure
  ALTER COLUMN drug_type_concept_id TYPE BIGINT;
ALTER TABLE IF EXISTS omop_drug_exposure
  ALTER COLUMN route_concept_id TYPE BIGINT;
ALTER TABLE IF EXISTS omop_drug_exposure
  ALTER COLUMN drug_source_concept_id TYPE BIGINT;

-- CONDITION_OCCURRENCE concept FKs
ALTER TABLE IF EXISTS omop_condition_occurrence
  ALTER COLUMN condition_concept_id_int TYPE BIGINT;
ALTER TABLE IF EXISTS omop_condition_occurrence
  ALTER COLUMN condition_type_concept_id TYPE BIGINT;
ALTER TABLE IF EXISTS omop_condition_occurrence
  ALTER COLUMN condition_status_concept_id TYPE BIGINT;
ALTER TABLE IF EXISTS omop_condition_occurrence
  ALTER COLUMN condition_source_concept_id TYPE BIGINT;

-- SIDER / in-label baseline pairings (created by SQLAlchemy if missing)
CREATE TABLE IF NOT EXISTS omop_drug_condition_baseline (
  id BIGSERIAL PRIMARY KEY,
  drug_concept_id BIGINT,
  condition_concept_id BIGINT,
  drug_source_value VARCHAR(256),
  condition_source_value VARCHAR(256),
  is_expected_baseline BOOLEAN NOT NULL DEFAULT TRUE,
  source VARCHAR(64) NOT NULL DEFAULT 'SIDER 4.1',
  project_id INTEGER,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_omop_baseline_drug
  ON omop_drug_condition_baseline (drug_concept_id);
CREATE INDEX IF NOT EXISTS ix_omop_baseline_cond
  ON omop_drug_condition_baseline (condition_concept_id);
CREATE INDEX IF NOT EXISTS ix_omop_baseline_expected
  ON omop_drug_condition_baseline (is_expected_baseline);
