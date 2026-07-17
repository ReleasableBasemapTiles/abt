-- =============================================================================
-- LAYER: Ferry
-- Schema:        export
-- Sources:       osm.osm_shipway_linestring
-- =============================================================================


-- -----------------------------------------------------------------------------
-- export.ferry_line — ferry route linestrings
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.ferry_line CASCADE;
CREATE MATERIALIZED VIEW export.ferry_line AS
SELECT
    osm_id,
    class,
    subclass,
    NULLIF(name, '')                                                    AS name,
    NULLIF(name_en, '')                                                 AS name_en,
    NULLIF(short_name, '')                                              AS short_name,
    NULLIF(shipway, '')                                                 AS shipway,
    NULLIF(service, '')                                                 AS service,
    NULLIF(usage, '')                                                   AS usage,
    is_bridge,
    is_tunnel,
    is_ramp,
    is_ford,
    is_oneway,
    layer,
    geometry
FROM osm.osm_shipway_linestring;

CREATE INDEX idx_ferry_geometry ON export.ferry_line USING gist(geometry);
CREATE INDEX idx_ferry_subclass ON export.ferry_line USING btree(subclass);
COMMIT;
