-- =============================================================================
-- LAYER: Glacier
-- Schema:        export
-- Intermediates: landcover.glacier_ne
--                landcover.glacier_osm
-- Sources:       aux_data.ne_10m_antarctic_ice_shelves_polys
--                aux_data.ne_10m_glaciated_areas
--                osm.osm_landcover_polygon
--                aux_data.osm_icesheet
-- =============================================================================


-- -----------------------------------------------------------------------------
-- SCHEMA
-- -----------------------------------------------------------------------------

BEGIN;
CREATE SCHEMA IF NOT EXISTS landcover;
COMMIT;


-- -----------------------------------------------------------------------------
-- landcover.glacier_ne — Natural Earth glaciated areas and Antarctic ice shelves
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS landcover.glacier_ne CASCADE;
CREATE MATERIALIZED VIEW landcover.glacier_ne AS
SELECT
    'ne'                                                            AS source,
    NULLIF(name, '')                                                AS name,
    (ST_Dump(
        ST_MakeValid(
            ST_SimplifyPreserveTopology(geometry, 0.000001),
            'method=structure'
        )
    )).geom::geometry(Polygon, 4326)                                AS geometry
FROM aux_data.ne_10m_antarctic_ice_shelves_polys
WHERE geometry IS NOT NULL

UNION ALL

SELECT
    'ne'                                                            AS source,
    NULLIF(name, '')                                                AS name,
    (ST_Dump(
        ST_MakeValid(
            ST_SimplifyPreserveTopology(geometry, 0.000001),
            'method=structure'
        )
    )).geom::geometry(Polygon, 4326)                                AS geometry
FROM aux_data.ne_10m_glaciated_areas
WHERE geometry IS NOT NULL;

CREATE INDEX idx_glacier_ne_geometry ON landcover.glacier_ne USING gist(geometry);
CREATE INDEX idx_glacier_ne_source   ON landcover.glacier_ne USING btree(source);
COMMIT;


-- -----------------------------------------------------------------------------
-- landcover.glacier_osm — OSM glacier polygons and Antarctica ice sheet
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS landcover.glacier_osm CASCADE;
CREATE MATERIALIZED VIEW landcover.glacier_osm AS
SELECT
    'osm'                                                           AS source,
    NULLIF(TRIM(tags -> 'name'), '')                                AS name,
    (ST_Dump(
        ST_MakeValid(
            ST_SimplifyPreserveTopology(geometry, 0.000001),
            'method=structure'
        )
    )).geom::geometry(Polygon, 4326)                                AS geometry
FROM osm.osm_landcover_polygon
WHERE subclass = 'glacier'
  AND geometry IS NOT NULL

UNION ALL

SELECT
    'osm'                                                           AS source,
    'antarctica_icesheet'                                           AS name,
    (ST_Dump(
        ST_MakeValid(
            ST_SimplifyPreserveTopology(geometry, 0.000001),
            'method=structure'
        )
    )).geom::geometry(Polygon, 4326)                                AS geometry
FROM aux_data.osm_icesheet
WHERE geometry IS NOT NULL;

CREATE INDEX idx_glacier_osm_geometry ON landcover.glacier_osm USING gist(geometry);
CREATE INDEX idx_glacier_osm_source   ON landcover.glacier_osm USING btree(source);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.glacier_polygon — unified output tile layer (NE + OSM)
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.glacier_polygon CASCADE;
CREATE MATERIALIZED VIEW export.glacier_polygon AS
SELECT
    source,
    name,
    geometry
FROM landcover.glacier_ne

UNION ALL

SELECT
    source,
    name,
    geometry
FROM landcover.glacier_osm;

CREATE INDEX idx_glacier_geometry ON export.glacier_polygon USING gist(geometry);
CREATE INDEX idx_glacier_source   ON export.glacier_polygon USING btree(source);
CREATE INDEX idx_glacier_name     ON export.glacier_polygon USING btree(name) WHERE name IS NOT NULL;
COMMIT;
