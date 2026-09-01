-- =============================================================================
-- LAYER: Physical Labels
-- Schema:  export
-- Sources: aux_data.ne_physical_centerlines  (static — see carto_sql/static_data/)
-- =============================================================================


-- -----------------------------------------------------------------------------
-- export.physical_labels
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.physical_labels CASCADE;
CREATE MATERIALIZED VIEW export.physical_labels AS
SELECT
    COALESCE(NULLIF(name_en, ''), NULLIF(name, ''))     AS name,
    NULLIF(featurecla, '')                              AS featurecla,
    scalerank,
    min_label,
    max_label,
    geometry
FROM aux_data.ne_physical_centerlines
WHERE NULLIF(name, '') IS NOT NULL;

CREATE INDEX idx_physical_labels_geometry  ON export.physical_labels USING gist(geometry);
CREATE INDEX idx_physical_labels_scalerank ON export.physical_labels USING btree(scalerank);
COMMIT;
