-- =============================================================================
-- LAYER: Culvert Points
-- Schema:        export
-- Sources:       osm.osm_water_point
--
-- Captures culvert nodes via two OSM tagging patterns:
--   waterway=culvert          — the node itself is a culvert
--   tunnel=culvert            — node on a waterway tagged as passing through a culvert
-- =============================================================================


BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.culvert_point CASCADE;
CREATE MATERIALIZED VIEW export.culvert_point AS
SELECT
    osm_id,
    NULLIF(name, '')                                                    AS name,
    NULLIF(name_en, '')                                                 AS name_en,
    subclass,
    geometry
FROM osm.osm_water_point
WHERE subclass = 'culvert'
   OR tunnel = 'culvert';

CREATE INDEX idx_culvert_point_geometry ON export.culvert_point USING gist(geometry);
CREATE INDEX idx_culvert_point_osm_id   ON export.culvert_point USING btree(osm_id);
COMMIT;
