-- =============================================================================
-- LAYER: Small-Scale Land Cover
-- Schema:        export
-- Intermediates: landcover.small_leveled,
--                landcover.small_src, landcover.small_urban (transient)
-- Sources:       aux_data.overture_land_cover
-- =============================================================================


-- -----------------------------------------------------------------------------
-- Small-scale (z0–z7) land cover from Overture's small-scale land cover band
-- (cartography.max_zoom <= 7, derived from ESA WorldCover). It replaces the
-- MODIS layer an earlier schema used at these zooms; the OSM-based
-- landcover_polygon takes over at larger scales, as set in the style.
--
-- The band is already smooth, so edges are left alone (tippecanoe simplifies
-- them with --detect-shared-borders, which keeps neighbouring classes'
-- shared edges identical). What clutters it at small scales is fragments:
-- small islands of one class inside another, and the matching holes. So each
-- zoom level z (4–7) keeps the polygons at least 3 pixels across at that zoom,
-- (3 * zres(z))² in Web Mercator area (= screen pixels at any latitude), and
-- fills non-city holes under the same size so a dropped island takes its
-- surrounding class rather than leaving a gap. z0–z3 show the z4 level.
--
-- urban is not a class here: builtup_polygon (007) draws cities, from
-- generalized Overture urban areas at z4–z6 and OSM land use from z7. The
-- holes the small-scale urban polygons leave are kept at every level,
-- whatever their size, so no forest or crop is ever drawn over a city. Where
-- built-up doesn't cover a whole city (OSM land use at z7 can be patchy),
-- the background shows instead.
-- -----------------------------------------------------------------------------

BEGIN;
CREATE SCHEMA IF NOT EXISTS landcover;
COMMIT;

BEGIN;
DROP TABLE IF EXISTS landcover.small_src, landcover.small_urban,
    landcover.small_leveled CASCADE;

-- Polygons, with Overture's snow named `ice` as in the older MODIS layer.
CREATE TABLE landcover.small_src AS
SELECT CASE subtype WHEN 'snow' THEN 'ice' ELSE subtype END        AS subclass,
       d.geom::geometry(Polygon, 4326)                               AS geometry
FROM aux_data.overture_land_cover,
     LATERAL ST_Dump(ST_MakeValid(geometry)) d
WHERE max_zoom <= 7
  AND subtype <> 'urban'
  AND ST_GeometryType(d.geom) = 'ST_Polygon';

CREATE TABLE landcover.small_urban AS
SELECT geometry
FROM aux_data.overture_land_cover
WHERE max_zoom <= 7 AND subtype = 'urban';

CREATE INDEX idx_landcover_small_urban_geometry ON landcover.small_urban USING gist(geometry);
COMMIT;

-- Web Mercator area, the unit zres is in. Clipped to Web Mercator's latitude
-- limit first: snow polygons reach 90°S and 90°N, which have no Mercator y.
BEGIN;
CREATE TABLE landcover.small_leveled AS
WITH levels AS (
    SELECT z, power(3 * zres(z), 2) AS min_area FROM generate_series(4, 7) AS z
),
src AS (
    SELECT subclass, geometry,
           ST_Area(ST_Transform(ST_Intersection(geometry,
               ST_MakeEnvelope(-180, -85.0511, 180, 85.0511, 4326)), 3857)) AS area
    FROM landcover.small_src
)
SELECT
    l.z                                                              AS z_level,
    s.subclass,
    ST_MakePolygon(
        ST_ExteriorRing(s.geometry),
        ARRAY(
            SELECT ST_ExteriorRing(r.geom)
            FROM ST_DumpRings(s.geometry) r
            WHERE r.path[1] > 0
              AND (
                  -- a city: always stays a hole, whatever its size
                  EXISTS (
                      SELECT 1 FROM landcover.small_urban u
                      WHERE u.geometry && r.geom
                        AND ST_Intersects(u.geometry, ST_PointOnSurface(r.geom))
                  )
                  -- anything else: stays only if at least the level's minimum
                  OR ST_Area(ST_Transform(ST_Intersection(r.geom,
                         ST_MakeEnvelope(-180, -85.0511, 180, 85.0511, 4326)), 3857)) >= l.min_area
              )
        )
    )::geometry(Polygon, 4326)                                       AS geometry
FROM src s
JOIN levels l ON s.area >= l.min_area;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.landcover_small_polygon
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.landcover_small_polygon CASCADE;
CREATE MATERIALIZED VIEW export.landcover_small_polygon AS
SELECT subclass, z_level, geometry
FROM landcover.small_leveled;

CREATE INDEX idx_landcover_small_geometry ON export.landcover_small_polygon USING gist(geometry);
CREATE INDEX idx_landcover_small_z_level  ON export.landcover_small_polygon USING btree(z_level);
COMMIT;

BEGIN;
DROP TABLE landcover.small_src, landcover.small_urban;
COMMIT;
