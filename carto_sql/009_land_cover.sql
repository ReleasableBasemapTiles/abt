-- =============================================================================
-- LAYER: Land Cover
-- Schema:        export
-- Intermediates: landcover.preprocessed, landcover.leveled,
--                landcover.z13_source .. landcover.z4_simplified (transient)
-- Sources:       osm.osm_landcover_polygon
-- =============================================================================


-- -----------------------------------------------------------------------------
-- SESSION TUNING — applies to every statement below (plain SET is
-- session-scoped and survives the BEGIN/COMMIT blocks)
-- -----------------------------------------------------------------------------

SET work_mem = '2GB';
SET maintenance_work_mem = '16GB';
SET max_parallel_workers_per_gather = 10;
SET parallel_setup_cost = 100;
SET parallel_tuple_cost = 0.01;
SET jit = off;
SET synchronous_commit = off;


-- -----------------------------------------------------------------------------
-- SCHEMA
-- -----------------------------------------------------------------------------

BEGIN;
CREATE SCHEMA IF NOT EXISTS landcover;
CREATE EXTENSION IF NOT EXISTS dblink;
COMMIT;


-- -----------------------------------------------------------------------------
-- landcover.preprocessed
-- -----------------------------------------------------------------------------

BEGIN;
DROP TABLE IF EXISTS landcover.preprocessed CASCADE;
CREATE TABLE landcover.preprocessed AS
WITH leafcycle AS (
    SELECT
        osm_id,
        NULLIF(TRIM(name), '')                                          AS name,
        NULLIF(TRIM(name_en), '')                                       AS name_en,

        CASE
            WHEN leaf_type ~ '^broad'  THEN 'broadleaved'
            WHEN leaf_type ~ '^con'    THEN 'coniferous'
            WHEN leaf_type ~ '^dec'    THEN 'deciduous'
            WHEN leaf_type ~ '^leaf'   THEN 'leafless'
            WHEN leaf_type ~ '^mix'    THEN 'mixed'
            WHEN leaf_type ~ '^needle' THEN 'needleleaved'
            ELSE NULL
        END                                                             AS leaf_type,

        CASE
            WHEN leaf_cycle IN ('deciduous', 'semi_deciduous')          THEN 'deciduous'
            WHEN leaf_cycle IN ('evergreen', 'semi_evergreen')          THEN 'evergreen'
            WHEN leaf_cycle ~ '^m'                                      THEN 'mixed'
            ELSE NULL
        END                                                             AS leaf_cycle_raw,

        -- Expand generic wetland subclass into specific wetland type
        CASE
            WHEN subclass = 'wetland' THEN
                CASE wetland
                    WHEN 'mangrove'     THEN 'mangrove'
                    WHEN 'bog'          THEN 'bog'
                    WHEN 'marsh'        THEN 'marsh'
                    WHEN 'swamp'        THEN 'swamp'
                    WHEN 'fen'          THEN 'fen'
                    WHEN 'saltmarsh'    THEN 'saltmarsh'
                    WHEN 'reedbed'      THEN 'reedbed'
                    WHEN 'wet_meadow'   THEN 'wet_meadow'
                    WHEN 'tidalflat'    THEN 'tidalflat'
                    WHEN 'string_bog'   THEN 'string_bog'
                    WHEN 'saltern'      THEN 'salt_flat'
                    ELSE                     'unknown_wetland'
                END
            ELSE subclass
        END                                                             AS subclass,

        CASE WHEN is_seasonal OR is_intermittent THEN true ELSE NULL END AS intermittent,
        ST_NPoints(geometry)                                            AS vertex_count,
        ST_Transform(geometry, 3857)                                    AS geometry
    FROM osm.osm_landcover_polygon
    WHERE ST_GeometryType(geometry) IN ('ST_Polygon', 'ST_MultiPolygon')
      AND geometry IS NOT NULL
),
classified AS (
    SELECT
        osm_id,
        name,
        name_en,
        subclass,
        intermittent,
        leaf_type,
        -- Infer leaf_cycle from leaf_type when not explicitly tagged
        CASE
            WHEN leaf_type IN ('coniferous', 'needleleaved') AND leaf_cycle_raw IS NULL THEN 'evergreen'
            WHEN leaf_type IN ('deciduous', 'broadleaved', 'leafless') AND leaf_cycle_raw IS NULL THEN 'deciduous'
            WHEN leaf_type = 'mixed' AND leaf_cycle_raw IS NULL THEN 'mixed'
            ELSE leaf_cycle_raw
        END                                                             AS leaf_cycle,
        vertex_count,
        ST_Area(geometry)::real                                         AS area,
        geometry
    FROM leafcycle
    WHERE subclass IN (
        -- Coastal / large landscape features (z4+)
        'bare_rock', 'beach', 'dune', 'dune_system', 'glacier', 'sand', 'scree', 'shoal',
        -- Wetlands (z6+)
        'bog', 'fen', 'mangrove', 'marsh', 'reedbed', 'salt_flat', 'saltmarsh',
        'string_bog', 'swamp', 'tidalflat', 'unknown_wetland', 'wet_meadow',
        -- Forest / wood (z7+)
        'forest', 'wood',
        -- Grassland / scrub / heath (z10+)
        'fell', 'flowerbed', 'grass', 'grassland', 'heath', 'meadow',
        'reef', 'scrub', 'tundra', 'village_green',
        -- Agriculture (z10+)
        'allotments', 'farm', 'farmland', 'orchard', 'paddy', 'rice', 'plant_nursery', 'vineyard'
    )
      -- Drop features too small to ever appear at z13 (some exemptions)
      AND (subclass IN ('reef', 'shoal', 'flowerbed') OR ST_Area(geometry) > power(zres(13), 2))
)
SELECT * FROM classified;

CREATE INDEX idx_landcover_prep_geometry ON landcover.preprocessed USING gist(geometry);
CREATE INDEX idx_landcover_prep_subclass ON landcover.preprocessed USING btree(subclass);
CREATE INDEX idx_landcover_prep_area     ON landcover.preprocessed USING btree(area);
CREATE INDEX idx_landcover_prep_osm_id   ON landcover.preprocessed USING btree(osm_id);
CREATE INDEX idx_landcover_prep_name     ON landcover.preprocessed USING btree(name) WHERE name IS NOT NULL;
COMMIT;


-- -----------------------------------------------------------------------------
-- Simplification cascade z13 → z4, staged as UNLOGGED tables.
--
-- Sequential by construction (each level derives from the previous), but each
-- CTAS is a parallelizable scan, and staging avoids the double CTE
-- materialization of the previous single-statement version.
--
-- Fixed-precision welding is handled by the gridSize argument of ST_Union in
-- the dissolve procedure (GEOS OverlayNG), so no SnapToGrid is needed here.
-- -----------------------------------------------------------------------------

BEGIN;
DROP TABLE IF EXISTS landcover.z13_source, landcover.z12_simplified,
    landcover.z11_simplified, landcover.z10_simplified, landcover.z9_simplified,
    landcover.z8_simplified,  landcover.z7_simplified,  landcover.z6_simplified,
    landcover.z5_simplified,  landcover.z4_simplified CASCADE;

CREATE UNLOGGED TABLE landcover.z13_source AS
SELECT subclass, leaf_type, leaf_cycle, intermittent, vertex_count,
       ST_MakeValid(geometry)                                           AS geometry
FROM landcover.preprocessed;

CREATE UNLOGGED TABLE landcover.z12_simplified AS
SELECT subclass, leaf_type, leaf_cycle, intermittent, vertex_count,
       ST_MakeValid(ST_SimplifyVW(geometry, power(zres(12), 2)))        AS geometry
FROM landcover.z13_source
WHERE ST_Area(geometry) > power(zres(11), 2);

CREATE UNLOGGED TABLE landcover.z11_simplified AS
SELECT subclass, leaf_type, leaf_cycle, intermittent, vertex_count,
       ST_MakeValid(ST_SimplifyVW(geometry, power(zres(11), 2)))        AS geometry
FROM landcover.z12_simplified
WHERE ST_Area(geometry) > power(zres(10), 2);

CREATE UNLOGGED TABLE landcover.z10_simplified AS
SELECT subclass, leaf_type, leaf_cycle, intermittent, vertex_count,
       ST_MakeValid(ST_SimplifyVW(geometry, power(zres(10), 2)))        AS geometry
FROM landcover.z11_simplified
WHERE ST_Area(geometry) > power(zres(9), 2);

CREATE UNLOGGED TABLE landcover.z9_simplified AS
SELECT subclass, leaf_type, leaf_cycle, intermittent, vertex_count,
       ST_MakeValid(ST_SimplifyVW(geometry, power(zres(9), 2)))         AS geometry
FROM landcover.z10_simplified
WHERE ST_Area(geometry) > power(zres(8), 2);

CREATE UNLOGGED TABLE landcover.z8_simplified AS
SELECT subclass, leaf_type, leaf_cycle, intermittent, vertex_count,
       ST_MakeValid(ST_SimplifyVW(geometry, power(zres(8), 2)))         AS geometry
FROM landcover.z9_simplified
WHERE ST_Area(geometry) > power(zres(7), 2);

CREATE UNLOGGED TABLE landcover.z7_simplified AS
SELECT subclass, leaf_type, leaf_cycle, intermittent, vertex_count,
       ST_MakeValid(ST_SimplifyVW(geometry, power(zres(7), 2)))         AS geometry
FROM landcover.z8_simplified
WHERE ST_Area(geometry) > power(zres(6), 2);

CREATE UNLOGGED TABLE landcover.z6_simplified AS
SELECT subclass, leaf_type, leaf_cycle, intermittent, vertex_count,
       ST_MakeValid(ST_SimplifyVW(geometry, power(zres(6), 2)))         AS geometry
FROM landcover.z7_simplified
WHERE ST_Area(geometry) > power(zres(5), 2);

CREATE UNLOGGED TABLE landcover.z5_simplified AS
SELECT subclass, leaf_type, leaf_cycle, intermittent, vertex_count,
       ST_MakeValid(ST_SimplifyVW(geometry, power(zres(5), 2)))         AS geometry
FROM landcover.z6_simplified
WHERE ST_Area(geometry) > power(zres(4), 2);

CREATE UNLOGGED TABLE landcover.z4_simplified AS
SELECT subclass, leaf_type, leaf_cycle, intermittent, vertex_count,
       ST_MakeValid(ST_SimplifyVW(geometry, power(zres(4), 2)))         AS geometry
FROM landcover.z5_simplified
WHERE ST_Area(geometry) > power(zres(3), 2);
COMMIT;


-- -----------------------------------------------------------------------------
-- landcover.leveled — per-zoom dissolved output rows, populated by the grid
--                     dissolve procedure below (replaces the ten global
--                     ST_ClusterDBSCAN window passes)
-- -----------------------------------------------------------------------------

BEGIN;
DROP TABLE IF EXISTS landcover.leveled CASCADE;
CREATE TABLE landcover.leveled (
    subclass     text,
    leaf_type    text,
    leaf_cycle   text,
    intermittent boolean,
    z_level      int,
    geometry     geometry(Polygon, 3857)
);

DROP TABLE IF EXISTS landcover.dissolve_jobs;
CREATE TABLE landcover.dissolve_jobs (
    z_level          int PRIMARY KEY,
    src              text NOT NULL,
    cluster_pred     text NOT NULL,
    passthrough_pred text
);

INSERT INTO landcover.dissolve_jobs VALUES
(13, 'landcover.z13_source',
     $$vertex_count < 300 AND subclass IN ('wood', 'forest')$$,
     $$(vertex_count >= 300 AND subclass IN ('wood', 'forest')) OR subclass NOT IN ('wood', 'forest')$$),
(12, 'landcover.z12_simplified',
     $$vertex_count < 300 AND subclass IN ('wood', 'forest')$$,
     $$(vertex_count >= 300 AND subclass IN ('wood', 'forest')) OR subclass NOT IN ('wood', 'forest')$$),
(11, 'landcover.z11_simplified',
     $$vertex_count < 300 AND subclass IN ('wood', 'forest')$$,
     $$(vertex_count >= 300 AND subclass IN ('wood', 'forest')) OR subclass NOT IN ('wood', 'forest')$$),
(10, 'landcover.z10_simplified',
     $$vertex_count < 300 AND subclass IN ('wood', 'forest')$$,
     $$(vertex_count >= 300 AND subclass IN ('wood', 'forest')) OR subclass NOT IN ('wood', 'forest')$$),
(9,  'landcover.z9_simplified',
     $$subclass IN ('wood', 'forest')$$,
     $$subclass IN ('bare_rock', 'beach', 'bog', 'dune', 'dune_system', 'fen', 'glacier',
                    'mangrove', 'marsh', 'reedbed', 'salt_flat', 'saltmarsh', 'sand', 'scree',
                    'shoal', 'string_bog', 'swamp', 'tidalflat', 'unknown_wetland', 'wet_meadow')$$),
(8,  'landcover.z8_simplified',
     $$subclass IN ('wood', 'forest')$$,
     $$subclass IN ('bare_rock', 'beach', 'bog', 'dune', 'dune_system', 'fen', 'glacier',
                    'mangrove', 'marsh', 'reedbed', 'salt_flat', 'saltmarsh', 'sand', 'scree',
                    'shoal', 'string_bog', 'swamp', 'tidalflat', 'unknown_wetland', 'wet_meadow')$$),
(7,  'landcover.z7_simplified',
     $$subclass IN ('bare_rock', 'beach', 'bog', 'dune', 'dune_system', 'fen', 'forest', 'glacier',
                    'mangrove', 'marsh', 'reedbed', 'salt_flat', 'saltmarsh', 'sand', 'scree',
                    'shoal', 'string_bog', 'swamp', 'tidalflat', 'unknown_wetland', 'wet_meadow', 'wood')$$,
     NULL),
(6,  'landcover.z6_simplified',
     $$subclass IN ('bare_rock', 'beach', 'bog', 'dune', 'dune_system', 'fen', 'glacier',
                    'mangrove', 'marsh', 'reedbed', 'salt_flat', 'saltmarsh', 'sand', 'scree',
                    'shoal', 'string_bog', 'swamp', 'tidalflat', 'unknown_wetland', 'wet_meadow')$$,
     NULL),
(5,  'landcover.z5_simplified',
     $$subclass IN ('bare_rock', 'beach', 'dune', 'dune_system', 'glacier', 'sand', 'scree', 'shoal')$$,
     NULL),
(4,  'landcover.z4_simplified',
     $$subclass IN ('bare_rock', 'beach', 'dune', 'dune_system', 'glacier', 'sand', 'scree', 'shoal')$$,
     NULL);
COMMIT;

-- Two-phase grid dissolve for one zoom level (same pattern as the water
-- dissolve in 005a): whole polygons binned into 100 km cells, unioned per cell
-- and attribute combination, then the cross-cell touchers merged exactly.
-- Temp tables are session-local, so concurrent workers never collide.
BEGIN;
CREATE OR REPLACE PROCEDURE landcover.dissolve_level(p_z int)
LANGUAGE plpgsql
AS $proc$
DECLARE
    cell CONSTANT int := 100000;    -- metres, EPSG:3857
    job  landcover.dissolve_jobs%ROWTYPE;
BEGIN
    SELECT * INTO STRICT job FROM landcover.dissolve_jobs WHERE z_level = p_z;
    RAISE NOTICE 'z% dissolve start %', p_z, clock_timestamp();

    EXECUTE 'DROP TABLE IF EXISTS _dis_src, _dis_p1, _dis_touch';

    EXECUTE format($q$
        CREATE TEMP TABLE _dis_src AS
        SELECT subclass, leaf_type, leaf_cycle, intermittent,
               floor((ST_XMin(geometry) + ST_XMax(geometry)) / 2.0 / %1$s)::int AS cell_x,
               floor((ST_YMin(geometry) + ST_YMax(geometry)) / 2.0 / %1$s)::int AS cell_y,
               ST_CollectionExtract(geometry, 3) AS geometry
        FROM %2$s
        WHERE (%3$s)
          AND NOT ST_IsEmpty(geometry)
    $q$, cell, job.src, job.cluster_pred);

    EXECUTE $q$
        CREATE TEMP TABLE _dis_p1 AS
        SELECT row_number() OVER () AS id,
               subclass, leaf_type, leaf_cycle, intermittent, cell_x, cell_y,
               d.geom AS geometry
        FROM (
            SELECT subclass, leaf_type, leaf_cycle, intermittent, cell_x, cell_y,
                   ST_Union(geometry, 0.001) AS merged
            FROM _dis_src
            GROUP BY subclass, leaf_type, leaf_cycle, intermittent, cell_x, cell_y
        ) g, LATERAL ST_Dump(g.merged) d
        WHERE ST_Dimension(d.geom) = 2
    $q$;
    EXECUTE 'CREATE INDEX ON _dis_p1 USING gist(geometry)';
    EXECUTE 'ANALYZE _dis_p1';

    EXECUTE $q$
        CREATE TEMP TABLE _dis_touch AS
        SELECT DISTINCT unnest(ARRAY[a.id, b.id]) AS id
        FROM _dis_p1 a
        JOIN _dis_p1 b
          ON a.id < b.id
         AND a.subclass = b.subclass
         AND a.leaf_type    IS NOT DISTINCT FROM b.leaf_type
         AND a.leaf_cycle   IS NOT DISTINCT FROM b.leaf_cycle
         AND a.intermittent IS NOT DISTINCT FROM b.intermittent
         AND a.geometry && b.geometry
         AND ST_Intersects(a.geometry, b.geometry)
        WHERE (a.cell_x <> b.cell_x OR a.cell_y <> b.cell_y)
    $q$;

    EXECUTE format($q$
        INSERT INTO landcover.leveled (subclass, leaf_type, leaf_cycle, intermittent, z_level, geometry)
        SELECT p.subclass, p.leaf_type, p.leaf_cycle, p.intermittent, %1$s, p.geometry
        FROM _dis_p1 p
        WHERE NOT EXISTS (SELECT 1 FROM _dis_touch t WHERE t.id = p.id)
        UNION ALL
        SELECT subclass, leaf_type, leaf_cycle, intermittent, %1$s, d.geom
        FROM (
            SELECT subclass, leaf_type, leaf_cycle, intermittent,
                   ST_Union(geometry, 0.001) AS merged
            FROM (
                SELECT p.*,
                       ST_ClusterIntersectingWin(p.geometry) OVER (
                           PARTITION BY p.subclass, p.leaf_type, p.leaf_cycle, p.intermittent
                       ) AS cid
                FROM _dis_p1 p JOIN _dis_touch t USING (id)
            ) c
            GROUP BY subclass, leaf_type, leaf_cycle, intermittent, cid
        ) m, LATERAL ST_Dump(m.merged) d
        WHERE ST_Dimension(d.geom) = 2
    $q$, p_z);

    IF job.passthrough_pred IS NOT NULL THEN
        EXECUTE format($q$
            INSERT INTO landcover.leveled (subclass, leaf_type, leaf_cycle, intermittent, z_level, geometry)
            SELECT subclass, leaf_type, leaf_cycle, intermittent, %1$s, d.geom
            FROM %2$s s, LATERAL ST_Dump(ST_CollectionExtract(s.geometry, 3)) d
            WHERE (%3$s)
              AND ST_Dimension(d.geom) = 2
        $q$, p_z, job.src, job.passthrough_pred);
    END IF;

    EXECUTE 'DROP TABLE IF EXISTS _dis_src, _dis_p1, _dis_touch';
    RAISE NOTICE 'z% dissolve done %', p_z, clock_timestamp();
END;
$proc$;
COMMIT;

-- Run all ten level dissolves in parallel worker connections (they are
-- independent once the cascade tables exist, which are committed above).
-- A failure in any worker propagates to this session and aborts the script.
-- temp_buffers must ride in the connection string: workers are fresh sessions
-- that inherit nothing from this one, and the setting only takes effect if set
-- before a session first touches a temp table. dissolve_level's temp tables
-- and GiST build overrun the 8MB default on large extracts.
DO $$
DECLARE
    zooms CONSTANT int[] := ARRAY[13, 12, 11, 10, 9, 8, 7, 6, 5, 4];
    connstr CONSTANT text := format(
        'dbname=%s options=''-c work_mem=2GB -c temp_buffers=4GB -c synchronous_commit=off -c jit=off''',
        current_database());
    z int;
    n int;
BEGIN
    FOREACH z IN ARRAY zooms LOOP
        PERFORM dblink_connect('lc_w' || z, connstr);
        PERFORM dblink_send_query('lc_w' || z,
            format('CALL landcover.dissolve_level(%s)', z));
    END LOOP;

    FOREACH z IN ARRAY zooms LOOP
        LOOP
            PERFORM * FROM dblink_get_result('lc_w' || z) AS t(res text);
            GET DIAGNOSTICS n = ROW_COUNT;
            EXIT WHEN n = 0;
        END LOOP;
        PERFORM dblink_disconnect('lc_w' || z);
    END LOOP;
EXCEPTION WHEN OTHERS THEN
    FOREACH z IN ARRAY zooms LOOP
        BEGIN
            PERFORM dblink_disconnect('lc_w' || z);
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END LOOP;
    RAISE;
END;
$$;

BEGIN;
ANALYZE landcover.leveled;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.landcover_polygon — thin MV over landcover.leveled
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.landcover_polygon CASCADE;
CREATE MATERIALIZED VIEW export.landcover_polygon AS
SELECT subclass, leaf_type, leaf_cycle, intermittent, z_level, area, geometry
FROM (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, z_level,
           ST_Area(geometry::geography)::real                           AS area,
           geometry
    FROM (
        SELECT subclass, leaf_type, leaf_cycle, intermittent, z_level,
               ST_Transform(geometry, 4326)                             AS geometry
        FROM landcover.leveled
    ) t
) a
WHERE area > 1;

CREATE INDEX idx_landcover_geometry   ON export.landcover_polygon USING gist(geometry);
CREATE INDEX idx_landcover_subclass   ON export.landcover_polygon USING btree(subclass);
CREATE INDEX idx_landcover_z_level    ON export.landcover_polygon USING btree(z_level);
CREATE INDEX idx_landcover_leaf_type  ON export.landcover_polygon USING btree(leaf_type)  WHERE leaf_type  IS NOT NULL;
CREATE INDEX idx_landcover_leaf_cycle ON export.landcover_polygon USING btree(leaf_cycle) WHERE leaf_cycle IS NOT NULL;
COMMIT;

BEGIN;
DROP TABLE landcover.z13_source, landcover.z12_simplified,
    landcover.z11_simplified, landcover.z10_simplified, landcover.z9_simplified,
    landcover.z8_simplified,  landcover.z7_simplified,  landcover.z6_simplified,
    landcover.z5_simplified,  landcover.z4_simplified;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.landcover_label — label points for named land cover polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.landcover_label CASCADE;
CREATE MATERIALIZED VIEW export.landcover_label AS
SELECT
    osm_id,
    name,
    name_en,
    subclass,
    leaf_type,
    leaf_cycle,
    intermittent,
    area,
    CASE
        WHEN area >= power(zres(4),  2) THEN 4
        WHEN area >= power(zres(5),  2) THEN 5
        WHEN area >= power(zres(6),  2) THEN 6
        WHEN area >= power(zres(7),  2) THEN 7
        WHEN area >= power(zres(8),  2) THEN 8
        WHEN area >= power(zres(9),  2) THEN 9
        WHEN area >= power(zres(10), 2) THEN 10
        WHEN area >= power(zres(11), 2) THEN 11
        ELSE 12
    END                                                             AS z_level,
    ST_PointOnSurface(
        ST_Transform(geometry, 4326)
    )::geometry(Point, 4326)                                        AS geometry
FROM landcover.preprocessed
WHERE name IS NOT NULL
   OR name_en IS NOT NULL;

CREATE INDEX idx_landcover_label_geometry ON export.landcover_label USING gist(geometry);
CREATE INDEX idx_landcover_label_subclass ON export.landcover_label USING btree(subclass);
CREATE INDEX idx_landcover_label_z_level  ON export.landcover_label USING btree(z_level);
CREATE INDEX idx_landcover_label_area     ON export.landcover_label USING btree(area) WHERE area IS NOT NULL;
CREATE INDEX idx_landcover_label_name     ON export.landcover_label USING btree(name) WHERE name IS NOT NULL;
COMMIT;
