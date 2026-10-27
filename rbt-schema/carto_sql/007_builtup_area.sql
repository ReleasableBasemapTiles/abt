-- =============================================================================
-- LAYER: Built-up Area
-- Schema:        export
-- Intermediates: landuse.builtuparea_osm
-- Sources:       osm.osm_builtup_area
-- =============================================================================


-- -----------------------------------------------------------------------------
-- SCHEMA
-- -----------------------------------------------------------------------------

BEGIN;
CREATE SCHEMA IF NOT EXISTS landuse;
COMMIT;


-- -----------------------------------------------------------------------------
-- Natural Earth urban areas are no longer part of this layer: the map shows
-- only OSM built-up area, from z7. Drop the NE view left by earlier runs.
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS landuse.builtuparea_ne CASCADE;
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
    (class = 'landuse' AND subclass IN (
        'residential', 'commercial', 'retail', 'industrial',
        'railway', 'brownfield', 'depot', 'garages', 'civic_admin',
        'construction', 'education', 'fairground', 'institutional'
    ))
    OR
    (class = 'amenity' AND subclass IN (
        'school', 'university', 'kindergarten', 'college', 'library'
    ))
  );

CREATE INDEX idx_builtuparea_osm_geometry ON landuse.builtuparea_osm USING gist(geometry);
CREATE INDEX idx_builtuparea_osm_class    ON landuse.builtuparea_osm USING btree(class);
CREATE INDEX idx_builtuparea_osm_subclass ON landuse.builtuparea_osm USING btree(subclass);
CREATE INDEX idx_builtuparea_osm_area     ON landuse.builtuparea_osm USING btree(area);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.builtup_polygon — output tile layer (OSM only; class stays 'osm' so
--                           existing style filters keep matching)
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.builtup_polygon CASCADE;
CREATE MATERIALIZED VIEW export.builtup_polygon AS
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
