-- =============================================================================
-- LAYER: Built-up Area
-- Schema:        export
-- Intermediates: landuse.builtuparea_osm
--                landuse.builtuparea_overture
--                landuse.bua_ov_opened .. landuse.bua_ov_final (transient)
-- Sources:       osm.osm_builtup_area
--                aux_data.overture_urban
-- =============================================================================


-- -----------------------------------------------------------------------------
-- SESSION TUNING — as in 009_land_cover.sql: the parallel worker count comes
-- from abt.parallel_workers_per_gather when the carto orchestrator sets it.
-- -----------------------------------------------------------------------------

SET work_mem = '1GB';
SELECT set_config('max_parallel_workers_per_gather',
                   COALESCE(current_setting('abt.parallel_workers_per_gather', true), '10'),
                   false);
SET jit = off;
SET synchronous_commit = off;


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
-- landuse.builtuparea_overture — small-scale (z4–z6) built-up areas, generalized
-- in the style of a JNC (1:2M) chart from Overture's satellite-derived urban
-- land cover (ESA WorldCover, 10 m). OSM land use takes over from z7.
--
-- The JNC spec: outline the contiguous pattern of buildings, leave out narrow
-- strips along roads and scattered outliers, and portray nothing under 4 nmi²
-- (13.72 km²). WorldCover's built-up class includes roads, so the order matters:
--   1. open  (shrink then grow by open_m)   strips roads and ribbons < 2*open_m
--   2. close (grow by close_m, dissolve, shrink back) merges the real clusters
--   3. drop patches, and fill holes, under min_m2
--   4. smooth (round out and in by smooth_m), then simplify by simplify_m
-- Closing first instead filled the farmland road grid: on Taiwan it gave
-- 7,292 km² against 2,344 km² this way (Natural Earth: 8,231 km²).
--
-- Distances are true metres, applied in Web Mercator scaled by k = 1/cos(lat)
-- of each feature. Each step is its own UNLOGGED table so the per-polygon
-- steps can run as parallel scans.
-- -----------------------------------------------------------------------------

BEGIN;
DROP TABLE IF EXISTS landuse.bua_ov_opened, landuse.bua_ov_merged,
    landuse.bua_ov_final, landuse.builtuparea_overture CASCADE;

-- 1. Opening, per source polygon. ST_YMax < 85 keeps clear of Web Mercator's
-- limit; there's no urban land cover that far north or south anyway.
-- The source has 5,060,166 polygons worldwide (release 2026-10-21.0), mostly
-- small pixel clusters. A polygon that can't contain a 150 m-radius disk
-- (area < π·150² ≈ 70,686 m²) is erased by the opening, so it's skipped
-- before any buffering rather than buffered to nothing.
CREATE UNLOGGED TABLE landuse.bua_ov_opened AS
WITH src AS (
    SELECT ST_Transform(geometry, 3857)                             AS g,
           1 / cos(radians(ST_Y(ST_PointOnSurface(geometry))))      AS k
    FROM aux_data.overture_urban
    WHERE geometry IS NOT NULL
      AND abs(ST_YMax(geometry)) < 85 AND abs(ST_YMin(geometry)) < 85
      AND ST_Area(geometry::geography) >= 70686
)
SELECT k, ST_Buffer(ST_Buffer(g, -150 * k, 'quad_segs=4'), 150 * k, 'quad_segs=4') AS g
FROM src;
COMMIT;

-- 2. Closing: grow each opened polygon by close_m, dissolve the ones that now
-- touch, then shrink the result back. Clustering is global rather than
-- per grid cell, so a city on a cell edge (London on the prime meridian)
-- can't be split in two.
BEGIN;
CREATE UNLOGGED TABLE landuse.bua_ov_merged AS
WITH grown AS (
    SELECT ST_Buffer(g, 200 * k, 'quad_segs=4') AS g
    FROM landuse.bua_ov_opened
    WHERE NOT ST_IsEmpty(g)
),
clustered AS (
    SELECT g, ST_ClusterDBSCAN(g, 0, 1) OVER () AS cid FROM grown
),
dissolved AS (
    SELECT ST_Union(g) AS g FROM clustered GROUP BY cid
)
SELECT k, (ST_Dump(ST_Buffer(g, -200 * k, 'quad_segs=4'))).geom AS g
FROM dissolved,
     LATERAL (SELECT 1 / cos(radians(ST_Y(ST_Transform(ST_PointOnSurface(g), 4326))))) AS s(k);
COMMIT;

-- 3–4. Minimum area (true m² = Mercator m² / k²), fill holes under it, smooth,
-- simplify, and keep what's still above the minimum.
BEGIN;
CREATE UNLOGGED TABLE landuse.bua_ov_final AS
WITH big AS (
    SELECT k, g FROM landuse.bua_ov_merged
    WHERE ST_Area(g) / (k * k) >= 13.72e6
),
filled AS (
    SELECT k,
           ST_MakePolygon(
               ST_ExteriorRing(g),
               ARRAY(SELECT ST_ExteriorRing(r.geom)
                     FROM ST_DumpRings(g) r
                     WHERE r.path[1] > 0
                       AND ST_Area(r.geom) / (k * k) >= 13.72e6)
           ) AS g
    FROM big
),
smoothed AS (
    SELECT k,
           ST_SimplifyPreserveTopology(
               ST_Buffer(ST_Buffer(ST_Buffer(g, 150 * k), -300 * k), 150 * k),
               50 * k
           ) AS g
    FROM filled
)
SELECT k, (ST_Dump(g)).geom AS g FROM smoothed;
COMMIT;

BEGIN;
CREATE TABLE landuse.builtuparea_overture AS
SELECT
    'overture'                                                      AS class,
    'urban'                                                         AS subclass,
    ST_Area(g)::real                                                AS area,
    ST_Transform(g, 4326)::geometry(Polygon, 4326)                  AS geometry
FROM landuse.bua_ov_final
WHERE ST_GeometryType(g) = 'ST_Polygon'
  AND ST_Area(g) / (k * k) >= 13.72e6;

CREATE INDEX idx_builtuparea_overture_geometry ON landuse.builtuparea_overture USING gist(geometry);
DROP TABLE landuse.bua_ov_opened, landuse.bua_ov_merged, landuse.bua_ov_final;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.builtup_polygon — output tile layer: class 'overture' (generalized,
-- z4–z6) and class 'osm' (detailed, z7+). The zoom split is the tippecanoe
-- filter in export/builtup_polygon.json. `area` is Web Mercator m² for both.
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.builtup_polygon CASCADE;
CREATE MATERIALIZED VIEW export.builtup_polygon AS
SELECT
    class,
    subclass,
    area,
    geometry
FROM landuse.builtuparea_overture

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
