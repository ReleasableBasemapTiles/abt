-- =============================================================================
-- LAYER: Points of Interest
-- Schema:        export
-- Sources:       osm.osm_poi_point
--                osm.osm_poi_polygon
-- =============================================================================


-- -----------------------------------------------------------------------------
-- poi schema
-- -----------------------------------------------------------------------------

BEGIN;
CREATE SCHEMA IF NOT EXISTS poi;
COMMIT;


-- -----------------------------------------------------------------------------
-- poi.classify — normalise subclass → class for wish-list POI types
-- -----------------------------------------------------------------------------

BEGIN;
CREATE OR REPLACE FUNCTION poi.classify(subclass text, mapping_key text)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
SELECT CASE
    WHEN subclass = 'hospital'                                                  THEN 'hospital'
    WHEN subclass = 'police'                                                    THEN 'police'
    WHEN subclass = 'fire_station'                                              THEN 'fire_station'
    WHEN subclass IN ('school', 'kindergarten')                                 THEN 'school'
    WHEN subclass IN ('university', 'college')                                  THEN 'college'
    WHEN subclass = 'townhall'                                                  THEN 'townhall'
    WHEN subclass = 'courthouse'                                                THEN 'courthouse'
    WHEN subclass = 'public_building'                                           THEN 'public_building'
    WHEN subclass = 'diplomatic'                                                THEN 'diplomatic'
    WHEN subclass = 'place_of_worship'                                          THEN 'place_of_worship'
    ELSE NULL
END;
$$;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.poi_point — wish-list POI points
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.poi_point CASCADE;
CREATE MATERIALIZED VIEW export.poi_point AS

SELECT
    osm_id,
    NULLIF(name, '')                                                    AS name,
    NULLIF(name_en, '')                                                 AS name_en,
    poi.classify(subclass, class)                                       AS class,
    subclass,
    NULLIF(religion, '')                                                AS religion,
    geometry
FROM osm.osm_poi_point
WHERE poi.classify(subclass, class) IS NOT NULL

UNION ALL

SELECT
    osm_id,
    NULLIF(name, '')                                                    AS name,
    NULLIF(name_en, '')                                                 AS name_en,
    poi.classify(subclass, class)                                       AS class,
    subclass,
    NULLIF(religion, '')                                                AS religion,
    ST_PointOnSurface(geometry)::geometry(Point, 4326)                  AS geometry
FROM osm.osm_poi_polygon
WHERE poi.classify(subclass, class) IS NOT NULL;

CREATE INDEX idx_poi_point_geometry ON export.poi_point USING gist(geometry);
CREATE INDEX idx_poi_point_class    ON export.poi_point USING btree(class);
COMMIT;
