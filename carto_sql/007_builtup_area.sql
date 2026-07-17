-- =============================================================================
-- LAYER: Built-up Area
-- Schema:        export
-- Intermediates: landuse.builtuparea_ne
--                landuse.builtuparea_osm
-- Sources:       aux_data.ne_10m_urban_areas
--                osm.osm_builtup_area
-- =============================================================================


-- -----------------------------------------------------------------------------
-- SCHEMA
-- -----------------------------------------------------------------------------

BEGIN;
CREATE SCHEMA IF NOT EXISTS landuse;
COMMIT;


-- -----------------------------------------------------------------------------
-- landuse.builtuparea_ne — Natural Earth urban area polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS landuse.builtuparea_ne CASCADE;
CREATE MATERIALIZED VIEW landuse.builtuparea_ne AS
SELECT
    'ne'                                                            AS class,
    featurecla                                                      AS subclass,
    ST_Area(ST_Transform(geometry, 3857))::real                     AS area,
    (ST_Dump(
        ST_MakeValid(
            ST_SimplifyPreserveTopology(geometry, 0.000001),
            'method=structure'
        )
    )).geom::geometry(Polygon, 4326)                                AS geometry
FROM aux_data.ne_10m_urban_areas
WHERE geometry IS NOT NULL;

CREATE INDEX idx_builtuparea_ne_geometry ON landuse.builtuparea_ne USING gist(geometry);
CREATE INDEX idx_builtuparea_ne_class    ON landuse.builtuparea_ne USING btree(class);
CREATE INDEX idx_builtuparea_ne_subclass ON landuse.builtuparea_ne USING btree(subclass);
CREATE INDEX idx_builtuparea_ne_area     ON landuse.builtuparea_ne USING btree(area);
COMMIT;


-- -----------------------------------------------------------------------------
-- landuse.builtuparea_osm — OSM landuse and populated-place polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS landuse.builtuparea_osm CASCADE;
CREATE MATERIALIZED VIEW landuse.builtuparea_osm AS
SELECT
    'osm'                                                           AS class,
    subclass,
    ST_Area(ST_Transform(geometry, 3857))::real                     AS area,
    (ST_Dump(
        ST_MakeValid(
            ST_SimplifyPreserveTopology(geometry, 0.000001),
            'method=structure'
        )
    )).geom::geometry(Polygon, 4326)                                AS geometry
FROM osm.osm_builtup_area
WHERE geometry IS NOT NULL
  AND (
    -- Place polygons: city/town/village/hamlet outlines
    (class = 'place' AND subclass IN ('city', 'town', 'village', 'hamlet'))
    OR
    -- Landuse: excludes cemetery and religious (have dedicated layers)
    (class = 'landuse' AND subclass NOT IN ('cemetery', 'religious'))
  );

CREATE INDEX idx_builtuparea_osm_geometry ON landuse.builtuparea_osm USING gist(geometry);
CREATE INDEX idx_builtuparea_osm_class    ON landuse.builtuparea_osm USING btree(class);
CREATE INDEX idx_builtuparea_osm_subclass ON landuse.builtuparea_osm USING btree(subclass);
CREATE INDEX idx_builtuparea_osm_area     ON landuse.builtuparea_osm USING btree(area);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.builtup_polygon — unified output tile layer (NE + OSM)
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.builtup_polygon CASCADE;
CREATE MATERIALIZED VIEW export.builtup_polygon AS
SELECT
    class,
    subclass,
    area,
    geometry
FROM landuse.builtuparea_ne

UNION ALL

SELECT
    class,
    subclass,
    area,
    geometry
FROM landuse.builtuparea_osm;

CREATE INDEX idx_builtuparea_geometry ON export.builtup_polygon USING gist(geometry);
CREATE INDEX idx_builtuparea_class    ON export.builtup_polygon USING btree(class);
CREATE INDEX idx_builtuparea_subclass ON export.builtup_polygon USING btree(subclass);
CREATE INDEX idx_builtuparea_area     ON export.builtup_polygon USING btree(area);
COMMIT;
