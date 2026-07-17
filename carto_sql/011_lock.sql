-- =============================================================================
-- LAYER: Lock
-- Schema:        export
-- Sources:       osm.osm_waterway_linestring
--                osm.osm_utility_point
-- =============================================================================


-- -----------------------------------------------------------------------------
-- export.lock_line — waterway lock and gate linestrings
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.lock_line CASCADE;
CREATE MATERIALIZED VIEW export.lock_line AS
SELECT
    osm_id,
    class,
    subclass,
    CASE WHEN is_intermittent THEN true ELSE NULL END                   AS intermittent,
    NULLIF(name, '')                                                    AS name,
    NULLIF(name_en, '')                                                 AS name_en,
    NULLIF(lock, '')                                                    AS lock,
    NULLIF(lock_name, '')                                               AS lock_name,
    tags,
    geometry
FROM osm.osm_waterway_linestring
WHERE subclass IN ('lock_gate', 'gate', 'lock', 'lock_basin', 'locks');

CREATE INDEX idx_lock_geometry ON export.lock_line USING gist(geometry);
CREATE INDEX idx_lock_osm_id   ON export.lock_line USING btree(osm_id);
CREATE INDEX idx_lock_subclass ON export.lock_line USING btree(subclass);
CREATE INDEX idx_lock_name     ON export.lock_line USING btree(name) WHERE name IS NOT NULL;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.lock_label — waterway lock and gate label points
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.lock_label CASCADE;
CREATE MATERIALIZED VIEW export.lock_label AS
SELECT
    osm_id,
    class,
    subclass,
    NULLIF(name, '')                                                    AS name,
    NULLIF(name_en, '')                                                 AS name_en,
    NULLIF(operator, '')                                                AS operator,
    NULLIF(seamark_name, '')                                            AS seamark_name,
    NULLIF(seamark_type, '')                                            AS seamark_type,
    NULLIF(service, '')                                                 AS service,
    NULLIF(access, '')                                                  AS access,
    NULLIF(lock, '')                                                    AS lock,
    NULLIF(gate_category, '')                                           AS gate_category,
    tags,
    geometry
FROM osm.osm_utility_point
WHERE subclass IN ('lock_gate', 'gate', 'lock_basin', 'lock')
   OR NULLIF(lock, '') IS NOT NULL
   OR NULLIF(gate_category, '') IS NOT NULL;

CREATE INDEX idx_lock_label_geometry ON export.lock_label USING gist(geometry);
CREATE INDEX idx_lock_label_osm_id   ON export.lock_label USING btree(osm_id);
CREATE INDEX idx_lock_label_subclass ON export.lock_label USING btree(subclass);
CREATE INDEX idx_lock_label_name     ON export.lock_label USING btree(name) WHERE name IS NOT NULL;
COMMIT;
