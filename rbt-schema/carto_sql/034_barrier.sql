-- =============================================================================
-- LAYER: Barriers
-- Schema:        export
-- Sources:       osm.osm_barrier_point
--                osm.osm_barrier_linestring
-- =============================================================================


-- -----------------------------------------------------------------------------
-- Barrier points and lines, as in the earlier ABT schema's osm_barrier_point /
-- osm_barrier_linestring layers. That schema's style draws them from z15
-- (lines) and z16 (points), so they're tiled at z13 only and overzoomed from
-- there. The imposm mappings already restrict both tables to the barrier
-- values that style uses (barrier_point.yml, barrier_linestring.yml).
-- -----------------------------------------------------------------------------


-- -----------------------------------------------------------------------------
-- export.barrier_point
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.barrier_point CASCADE;
CREATE MATERIALIZED VIEW export.barrier_point AS
SELECT
    osm_id,
    subclass,
    COALESCE(NULLIF(name_en, ''), NULLIF(name, ''))                     AS name,
    geometry
FROM osm.osm_barrier_point;

CREATE INDEX idx_barrier_point_geometry ON export.barrier_point USING gist(geometry);
CREATE INDEX idx_barrier_point_subclass ON export.barrier_point USING btree(subclass);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.barrier_line
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.barrier_line CASCADE;
CREATE MATERIALIZED VIEW export.barrier_line AS
SELECT
    osm_id,
    subclass,
    COALESCE(NULLIF(name_en, ''), NULLIF(name, ''))                     AS name,
    geometry
FROM osm.osm_barrier_linestring;

CREATE INDEX idx_barrier_line_geometry ON export.barrier_line USING gist(geometry);
CREATE INDEX idx_barrier_line_subclass ON export.barrier_line USING btree(subclass);
COMMIT;
