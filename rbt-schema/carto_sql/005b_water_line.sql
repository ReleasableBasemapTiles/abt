-- =============================================================================
-- LAYER: Water — Linestrings
-- Schema:        export
-- Intermediates: water.waterway_relation_union
-- Sources:       osm.osm_waterway_relation
--                osm.osm_waterway_linestring
-- Depends on:    005a_water_polygon.sql (water schema + classify_water_type function)
-- =============================================================================


-- -----------------------------------------------------------------------------
-- waterway_brunnel — computes brunnel value from bridge/tunnel flags
-- -----------------------------------------------------------------------------

BEGIN;
CREATE OR REPLACE FUNCTION water.waterway_brunnel(is_bridge bool, is_tunnel bool)
RETURNS text AS $$
SELECT CASE
    WHEN is_bridge  THEN 'bridge'
    WHEN is_tunnel  THEN 'tunnel'
    ELSE NULL
END;
$$ LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE;
COMMIT;


-- -----------------------------------------------------------------------------
-- water.waterway_relation_union — relation members merged into full river lines
--
-- Unions waterway_relation member geometries by osm_id + name, keeping only
-- main_stream or unroled members and non-closed linestrings.  The resulting
-- geom_len reflects the full named river length rather than individual segments,
-- which is what drives the low-zoom z_level thresholds (z6–z9).
-- -----------------------------------------------------------------------------

BEGIN;
DROP TABLE IF EXISTS water.waterway_relation_union CASCADE;
CREATE TABLE water.waterway_relation_union AS
SELECT
    r.osm_id,
    NULLIF(r.name, '')                                              AS name,
    ST_Union(r.geometry)                                            AS geometry,
    ST_Length(ST_Transform(ST_Union(r.geometry), 3857))::real       AS geom_len,
    -- Mark intermittent only if ALL member segments are intermittent.
    -- Mixed rivers show as solid at z6-z9; per-segment detail appears at z10+.
    BOOL_AND(COALESCE(w.is_intermittent, false))                    AS is_intermittent
FROM osm.osm_waterway_relation r
LEFT JOIN osm.osm_waterway_linestring w ON w.osm_id = r.member
WHERE (r.role = 'main_stream' OR r.role = '')
  AND ST_GeometryType(r.geometry) = 'ST_LineString'
  AND ST_IsClosed(r.geometry) = FALSE
GROUP BY r.osm_id, r.name;

CREATE INDEX idx_waterway_relation_union_geometry ON water.waterway_relation_union USING gist(geometry);
CREATE INDEX idx_waterway_relation_union_osm_id   ON water.waterway_relation_union USING btree(osm_id);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.water_line — waterway linestring layer
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.water_line CASCADE;
CREATE MATERIALIZED VIEW export.water_line AS

-- Relation-merged rivers: length reflects full named river, drives z6–z9.
-- Capped at z9 in tippecanoe filter — individual segments take over at z10+
SELECT
    name,
    CASE WHEN is_intermittent THEN true ELSE NULL END               AS intermittent,
    'river'::text                                                   AS subclass,
    NULL::text                                                      AS brunnel,
    NULL::boolean                                                   AS culvert,
    geom_len,
    geometry,
    CASE
        WHEN geom_len >= 500000 THEN 6
        WHEN geom_len >= 400000 THEN 7
        WHEN geom_len >= 300000 THEN 8
        ELSE 9
    END                                                             AS z_level
FROM water.waterway_relation_union

UNION ALL

-- Individual OSM segments: z10+ per-segment intermittent values
SELECT
    NULLIF(name, '')                                                AS name,
    CASE WHEN is_intermittent THEN true ELSE NULL END               AS intermittent,
    water.classify_water_type(subclass)                             AS subclass,
    water.waterway_brunnel(is_bridge, is_tunnel)                    AS brunnel,
    CASE WHEN tunnel_type = 'culvert' THEN true ELSE NULL END       AS culvert,
    ST_Length(ST_Transform(geometry, 3857))::real                   AS geom_len,
    geometry,
    CASE
        WHEN water.classify_water_type(subclass) IN ('river', 'canal') THEN 10
        WHEN water.classify_water_type(subclass) = 'stream'
             AND ST_Length(ST_Transform(geometry, 3857)) >= 10000   THEN 11
        WHEN water.classify_water_type(subclass)
             IN ('stream', 'drain', 'ditch', 'creek')               THEN 12
        ELSE 13
    END                                                             AS z_level
FROM osm.osm_waterway_linestring
WHERE subclass IN (
    'canal', 'ditch', 'drain', 'river', 'stream', 'pond', 'lake', 'reservoir',
    'basin', 'wastewater', 'weir', 'rapids', 'oxbow', 'drystream',
    'tidal_channel', 'artificial', 'lagoon', 'fishpond', 'yes', 'waterfall',
    'derelict_canal', 'intermittent', 'brook', 'harbour', 'drainage_channel',
    'connector', 'sluice_gate', 'lake;pond', 'tidal', 'sewer', 'spillway',
    'construction', 'pan', 'riverbank', 'water', 'stream;river', 'culvert',
    'underground_drain', 'tunnel', 'drainage_gutter', 'sewage', 'abandoned',
    'creek', 'navigation', 'seaway', 'riverbed', 'lake;reservoir', 'razed',
    'pond;reservoir', 'unclassified', 'disused_canal', 'sluice', 'duct',
    'piscina', 'glacial_lage', 'seasonal', 'old_river', 'channel',
    'river;canal', 'strait', 'ocean'
);

CREATE INDEX idx_waterway_geometry ON export.water_line USING gist(geometry);
CREATE INDEX idx_waterway_subclass ON export.water_line USING btree(subclass);
CREATE INDEX idx_waterway_geom_len ON export.water_line USING btree(geom_len);
CREATE INDEX idx_waterway_z_level  ON export.water_line USING btree(z_level);
CREATE INDEX idx_waterway_name     ON export.water_line USING btree(name) WHERE name IS NOT NULL;
COMMIT;
