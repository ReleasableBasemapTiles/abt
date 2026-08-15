-- =============================================================================
-- LAYER: Pier / Breakwater / Groyne
-- Schema:        export
-- Sources:       osm.osm_pier_linestring
--                osm.osm_pier_polygon
-- =============================================================================


-- -----------------------------------------------------------------------------
-- export.pier_line — pier, breakwater, and groyne linestrings
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.pier_line CASCADE;
CREATE MATERIALIZED VIEW export.pier_line AS
SELECT
    osm_id,
    NULLIF(name, '')                                                    AS name,
    class,
    subclass,
    CASE WHEN is_floating THEN true ELSE NULL END                       AS is_floating,
    geometry
FROM osm.osm_pier_linestring
WHERE geometry IS NOT NULL;

CREATE INDEX idx_pier_line_geometry ON export.pier_line USING gist(geometry);
CREATE INDEX idx_pier_line_subclass ON export.pier_line USING btree(subclass);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.pier_polygon — pier, breakwater, and groyne polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.pier_polygon CASCADE;
CREATE MATERIALIZED VIEW export.pier_polygon AS
SELECT
    osm_id,
    NULLIF(name, '')                                                    AS name,
    class,
    subclass,
    CASE WHEN is_floating THEN true ELSE NULL END                       AS is_floating,
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area,
    geometry
FROM osm.osm_pier_polygon
WHERE geometry IS NOT NULL;

CREATE INDEX idx_pier_polygon_geometry ON export.pier_polygon USING gist(geometry);
CREATE INDEX idx_pier_polygon_subclass ON export.pier_polygon USING btree(subclass);
COMMIT;
