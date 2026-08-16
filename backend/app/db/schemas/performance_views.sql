-- =============================================================================
-- VigilAI Phase 1 — Performance layer (materialized views)
-- =============================================================================
-- omop_signal_summary: drug × condition unique-patient counts for UI / DMA prep.
-- UNIQUE INDEX on (drug_concept_id, condition_concept_id) enables
--   REFRESH MATERIALIZED VIEW CONCURRENTLY
-- during background ETL jobs without blocking readers.
-- =============================================================================

DROP MATERIALIZED VIEW IF EXISTS omop_signal_summary CASCADE;

CREATE MATERIALIZED VIEW omop_signal_summary AS
SELECT
    de.drug_concept_id,
    co.condition_concept_id,
    COUNT(DISTINCT de.person_id) AS exposure_count
FROM drug_exposure AS de
INNER JOIN condition_occurrence AS co
    ON co.person_id = de.person_id
GROUP BY
    de.drug_concept_id,
    co.condition_concept_id
WITH NO DATA;

-- Required for REFRESH MATERIALIZED VIEW CONCURRENTLY
CREATE UNIQUE INDEX uq_omop_signal_summary_drug_condition
    ON omop_signal_summary (drug_concept_id, condition_concept_id);

-- Supporting lookup indexes for UI filters / joins
CREATE INDEX idx_omop_signal_summary_drug
    ON omop_signal_summary (drug_concept_id);

CREATE INDEX idx_omop_signal_summary_condition
    ON omop_signal_summary (condition_concept_id);

CREATE INDEX idx_omop_signal_summary_exposure_count
    ON omop_signal_summary (exposure_count DESC);

-- First population (non-concurrent). Subsequent ETL jobs should run:
--   REFRESH MATERIALIZED VIEW CONCURRENTLY omop_signal_summary;
REFRESH MATERIALIZED VIEW omop_signal_summary;
