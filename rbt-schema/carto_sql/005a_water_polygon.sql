-- =============================================================================
-- LAYER: Water — Polygons
-- Schema:        export
-- Intermediates: water.water_surface
--                water.valid_ocean
--                water.water_surface_parts
--                water.inland_water_intermittent_parts
--                water.water_polygon_parts
-- Sources:       osm.osm_water_polygon
--                aux_data.osm_ocean
--                aux_data.ne_50m_ocean
--                aux_data.ne_50m_lakes
-- =============================================================================


-- -----------------------------------------------------------------------------
-- SESSION TUNING — applies to every statement below (plain SET is
-- session-scoped and survives the BEGIN/COMMIT blocks)
--
-- max_parallel_workers_per_gather and the dissolve's dblink shard count
-- (below) are read from the abt.parallel_workers_per_gather / abt.dissolve_shards
-- custom GUCs when set (e.g. by the carto orchestrator scaling them down
-- for concurrent carto_sql execution -- see rbt-schema/carto_sql/execution_plan.yml),
-- falling back to these historical single-script-at-a-time values otherwise.
-- -----------------------------------------------------------------------------

SET work_mem = '2GB';
SET maintenance_work_mem = '16GB';
SELECT set_config('max_parallel_workers_per_gather',
                   COALESCE(current_setting('abt.parallel_workers_per_gather', true), '10'),
                   false);
SET parallel_setup_cost = 100;
SET parallel_tuple_cost = 0.01;
SET jit = off;
SET synchronous_commit = off;


-- -----------------------------------------------------------------------------
-- SCHEMA
-- -----------------------------------------------------------------------------

BEGIN;
CREATE SCHEMA IF NOT EXISTS water;
COMMIT;


-- -----------------------------------------------------------------------------
-- water.classify_water_type — normalises raw OSM subclass strings to a
--                              controlled water-type vocabulary
-- -----------------------------------------------------------------------------

BEGIN;
CREATE OR REPLACE FUNCTION water.classify_water_type(subclass_input text)
RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
AS $$
BEGIN
    IF subclass_input IS NULL OR subclass_input = '' THEN
        RETURN 'water';
    END IF;

    RETURN CASE
        WHEN subclass_input ~ '^bas'          THEN 'basin'
        WHEN subclass_input ~ 'bayou'         THEN 'bayou'
        WHEN subclass_input ~ 'can[ao]l'      THEN 'canal'
        WHEN subclass_input ~ 'lake'          THEN 'lake'
        WHEN subclass_input ~ 'pool'          THEN 'pool'
        WHEN subclass_input ~ 'pond'          THEN 'pond'
        WHEN subclass_input ~ 'res[eo]rvoir'  THEN 'reservoir'
        WHEN subclass_input ~ 'cove'          THEN 'cove'
        WHEN subclass_input ~ 'creek'         THEN 'creek'
        WHEN subclass_input ~ 'spring'        THEN 'spring'
        WHEN subclass_input ~ 'river'         THEN 'river'
        WHEN subclass_input ~ 'ditch'         THEN 'ditch'
        WHEN subclass_input ~ 'stream'        THEN 'stream'
        WHEN subclass_input ~ '^est'          THEN 'estuary'
        WHEN subclass_input ~ 'fall'          THEN 'falls'
        WHEN subclass_input ~ '^fj[oi]'       THEN 'fjord'
        WHEN subclass_input ~ '^ha[rv]bou?r'  THEN 'harbour'
        WHEN subclass_input ~ 'lag[ou]'       THEN 'lagoon'
        WHEN subclass_input ~ 'ocean'         THEN 'ocean'
        WHEN subclass_input ~ '^rapi'         THEN 'rapids'
        WHEN subclass_input ~ 'o[xs]bow'      THEN 'oxbow'
        WHEN subclass_input ~ '^tidal'        THEN 'tidal'
        WHEN subclass_input ~ '^waste'        THEN 'wastewater'
        WHEN subclass_input = 'yes'           THEN 'water'
        ELSE subclass_input
    END;
END;
$$;
COMMIT;


-- -----------------------------------------------------------------------------
-- water.safe_simplify_geometry — validates geometry before simplification;
--                                 returns original on unexpected error
-- -----------------------------------------------------------------------------

BEGIN;
CREATE OR REPLACE FUNCTION water.safe_simplify_geometry(geom geometry, tolerance float8)
RETURNS geometry
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
AS $$
BEGIN
    IF NOT ST_IsValid(geom) THEN
        geom := ST_MakeValid(geom, 'method=structure');
    END IF;
    RETURN ST_SimplifyPreserveTopology(geom, tolerance);
EXCEPTION WHEN OTHERS THEN
    RETURN geom;
END;
$$;
COMMIT;


-- -----------------------------------------------------------------------------
-- water.water_surface — classified, simplified permanent water polygons
--
-- Per-row classify/validate/simplify over the full osm.osm_water_polygon
-- table, fanned out over 16 dblink workers sharded by abs(osm_id) % 16
-- (osm_id is signed — imposm negative-ids relations) into the UNLOGGED
-- staging table water.water_surface_parts. The materialized view is a
-- trivial copy plus the cheap water_type derivation.
-- -----------------------------------------------------------------------------

BEGIN;
CREATE EXTENSION IF NOT EXISTS dblink;
DROP MATERIALIZED VIEW IF EXISTS water.water_surface CASCADE;
DROP TABLE IF EXISTS water.water_surface_parts CASCADE;
CREATE UNLOGGED TABLE water.water_surface_parts (
    osm_id      bigint,
    name        text,
    subclass    text,
    water_tag   text,
    area        real,
    geometry    geometry(Geometry, 4326),
    intermittent text
);
COMMIT;

-- osm.osm_water_polygon is a source table (not written by this script), so
-- no COMMIT is needed before the workers connect.
DO $$
DECLARE
    nshards CONSTANT int := COALESCE(current_setting('abt.dissolve_shards', true)::int, 16);
    connstr CONSTANT text := format(
        'dbname=%s port=%s options=''-c work_mem=1GB -c synchronous_commit=off -c jit=off''',
        current_database(), current_setting('port'));
    i int;
    n int;
BEGIN
    FOR i IN 0 .. nshards - 1 LOOP
        PERFORM dblink_connect('wsurf_w' || i, connstr);
        PERFORM dblink_send_query('wsurf_w' || i, format($q$
            INSERT INTO water.water_surface_parts
                (osm_id, name, subclass, water_tag, area, geometry, intermittent)
            SELECT
                osm_id,
                COALESCE(NULLIF(name_en, ''), NULLIF(name, '')),
                water.classify_water_type(subclass),
                NULLIF(tags->'water', ''),
                ST_Area(ST_Transform(geometry, 3857))::real,
                water.safe_simplify_geometry(geometry, 0.000001),
                intermittent
            FROM osm.osm_water_polygon
            WHERE intermittent = 'f'
              AND geometry IS NOT NULL
              AND abs(osm_id) %% %s = %s
              AND water.classify_water_type(subclass) IN (
                'artificial', 'basin', 'bay', 'bayou', 'brook', 'canal', 'cenote',
                'channel', 'connector', 'canoe_pass', 'cove', 'creek', 'derelict_canal',
                'disused_canal', 'ditch', 'drain', 'estuary', 'falls', 'fish_pass',
                'fishpond', 'fjord', 'glacial_lage', 'guelta', 'gulf', 'harbour',
                'lagoon', 'lake', 'lake;pond', 'lake;reservoir', 'moat', 'ocean',
                'old_river', 'oxbow', 'pan', 'piscina', 'pond', 'pond;reservoir',
                'pool', 'rapids', 'reservoir', 'river', 'river;canal', 'riverbank',
                'riverbed', 'salt_pond', 'sea', 'sound', 'spillway', 'spring',
                'swimming_pool', 'strait', 'stream', 'stream_pool', 'stream;river',
                'tidal', 'tidal_channel', 'unclassified', 'wastewater', 'water',
                'waterfall', 'yes'
              )
        $q$, nshards, i));
    END LOOP;

    FOR i IN 0 .. nshards - 1 LOOP
        LOOP
            PERFORM * FROM dblink_get_result('wsurf_w' || i) AS t(res text);
            GET DIAGNOSTICS n = ROW_COUNT;
            EXIT WHEN n = 0;
        END LOOP;
        PERFORM dblink_disconnect('wsurf_w' || i);
    END LOOP;
EXCEPTION WHEN OTHERS THEN
    FOR i IN 0 .. nshards - 1 LOOP
        BEGIN
            PERFORM dblink_disconnect('wsurf_w' || i);
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END LOOP;
    RAISE;
END;
$$;

BEGIN;
CREATE MATERIALIZED VIEW water.water_surface AS
SELECT
    osm_id,
    name,
    subclass,
    -- Effective water type. subclass is the imposm mapping VALUE, which for
    -- modern tagging (natural=water + water=river) is just 'water' — the
    -- river-ness lives only in the water=* tag. Without this column, linear
    -- water cannot be told apart from lakes downstream.
    CASE
        WHEN water_tag IS NOT NULL THEN water.classify_water_type(water_tag)
        ELSE subclass
    END                                                         AS water_type,
    intermittent,
    area,
    geometry
FROM water.water_surface_parts;

CREATE INDEX idx_water_surface_geometry ON water.water_surface USING gist(geometry);
CREATE INDEX idx_water_surface_osm_id   ON water.water_surface USING btree(osm_id);
CREATE INDEX idx_water_surface_subclass ON water.water_surface USING btree(subclass);
CREATE INDEX idx_water_surface_area     ON water.water_surface USING btree(area);
CREATE INDEX idx_water_surface_name     ON water.water_surface USING btree(name) WHERE name IS NOT NULL;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.inland_water_intermittent_polygon — seasonal / intermittent water polygons
--
-- Same per-row validate/simplify shape as water.water_surface above (just
-- the intermittent/seasonal slice), same 16-worker dblink fan-out into
-- water.inland_water_intermittent_parts.
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.inland_water_intermittent_polygon CASCADE;
DROP TABLE IF EXISTS water.inland_water_intermittent_parts CASCADE;
CREATE UNLOGGED TABLE water.inland_water_intermittent_parts (
    osm_id      bigint,
    name        text,
    subclass    text,
    geometry    geometry(Polygon, 4326),
    area        real,
    intermittent text
);
COMMIT;

DO $$
DECLARE
    nshards CONSTANT int := COALESCE(current_setting('abt.dissolve_shards', true)::int, 16);
    connstr CONSTANT text := format(
        'dbname=%s port=%s options=''-c work_mem=1GB -c synchronous_commit=off -c jit=off''',
        current_database(), current_setting('port'));
    i int;
    n int;
BEGIN
    FOR i IN 0 .. nshards - 1 LOOP
        PERFORM dblink_connect('wintw_w' || i, connstr);
        PERFORM dblink_send_query('wintw_w' || i, format($q$
            INSERT INTO water.inland_water_intermittent_parts
                (osm_id, name, subclass, geometry, area, intermittent)
            SELECT
                osm_id,
                COALESCE(NULLIF(name_en, ''), NULLIF(name, '')),
                water.classify_water_type(subclass),
                (ST_Dump(
                    ST_MakeValid(
                        ST_SimplifyPreserveTopology(geometry, 0.000001),
                        'method=structure'
                    )
                )).geom::geometry(Polygon, 4326),
                ST_Area(ST_Transform(geometry, 3857))::real,
                intermittent
            FROM osm.osm_water_polygon
            WHERE (intermittent = 't' OR subclass IN ('intermittent', 'seasonal', 'drystream'))
              AND geometry IS NOT NULL
              AND abs(osm_id) %% %s = %s
        $q$, nshards, i));
    END LOOP;

    FOR i IN 0 .. nshards - 1 LOOP
        LOOP
            PERFORM * FROM dblink_get_result('wintw_w' || i) AS t(res text);
            GET DIAGNOSTICS n = ROW_COUNT;
            EXIT WHEN n = 0;
        END LOOP;
        PERFORM dblink_disconnect('wintw_w' || i);
    END LOOP;
EXCEPTION WHEN OTHERS THEN
    FOR i IN 0 .. nshards - 1 LOOP
        BEGIN
            PERFORM dblink_disconnect('wintw_w' || i);
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END LOOP;
    RAISE;
END;
$$;

BEGIN;
CREATE MATERIALIZED VIEW export.inland_water_intermittent_polygon AS
SELECT * FROM water.inland_water_intermittent_parts;

CREATE INDEX idx_inland_water_intermittent_geometry ON export.inland_water_intermittent_polygon USING gist(geometry);
CREATE INDEX idx_inland_water_intermittent_osm_id   ON export.inland_water_intermittent_polygon USING btree(osm_id);
CREATE INDEX idx_inland_water_intermittent_subclass ON export.inland_water_intermittent_polygon USING btree(subclass);
CREATE INDEX idx_inland_water_intermittent_area     ON export.inland_water_intermittent_polygon USING btree(area);
CREATE INDEX idx_inland_water_intermittent_name     ON export.inland_water_intermittent_polygon USING btree(name) WHERE name IS NOT NULL;
COMMIT;

-- -----------------------------------------------------------------------------
-- water.valid_ocean — validated ocean polygons, subdivided to ≤1024 vertices.
--                     OSM coastline polygons can carry 500k+ vertices and
--                     thousands of rings in marshland; tile-side clipping and
--                     simplification of those produces self-intersection
--                     rendering artifacts. Subdivision edges are invisible
--                     because the ocean style has no fill outline.
-- -----------------------------------------------------------------------------

BEGIN;
DROP TABLE IF EXISTS water.valid_ocean CASCADE;
CREATE TABLE water.valid_ocean AS
SELECT
    'ocean'                                                         AS subclass,
    s.geom::geometry(Polygon, 4326)                                 AS geometry
FROM (
    SELECT (ST_Dump(
        ST_MakeValid(
            ST_SimplifyPreserveTopology(
                ST_MakeValid(geometry, 'method=structure'),
                0.000001
            ),
            'method=structure'
        )
    )).geom AS geom
    FROM aux_data.osm_ocean
    WHERE geometry IS NOT NULL
      AND NOT ST_IsEmpty(geometry)
) d,
LATERAL ST_Subdivide(d.geom, 1024) AS s(geom)
WHERE ST_Dimension(d.geom) = 2;

CREATE INDEX idx_valid_ocean_geometry ON water.valid_ocean USING gist(geometry);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.ocean_polygon — ocean polygons with NE/OSM zoom transition
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.ocean_polygon CASCADE;
CREATE MATERIALIZED VIEW export.ocean_polygon AS

SELECT
    'ocean'::text                                                    AS subclass,
    ST_MakeValid(
        (ST_Dump(geometry)).geom::geometry(Polygon, 4326),
        'method=structure'
    )                                                                AS geometry,
    0                                                                AS z_level
FROM aux_data.ne_50m_ocean
WHERE geometry IS NOT NULL
  AND NOT ST_IsEmpty(geometry)

UNION ALL

SELECT
    subclass::text,
    ST_MakeValid(geometry, 'method=structure')                       AS geometry,
    1                                                                AS z_level
FROM water.valid_ocean;

CREATE INDEX idx_ocean_geometry         ON export.ocean_polygon USING gist(geometry);
CREATE INDEX idx_ocean_polygon_z_level  ON export.ocean_polygon USING btree(z_level);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.water_polygon — inland water polygons (NE 50m lakes + OSM)
--
-- Key discovery: the map style (RBT-TOPO) only draws a fill-outline stroke
-- on water_polygon from z12 on (fill-outline-color steps transparent ->
-- opaque exactly at z12). Below z12, touching same-colored fills are
-- visually indistinguishable from one merged shape whether or not they're
-- actually unioned. So:
--
--   z < 12  (no stroke): every feature, including touching ones, is
--           exported individually at its own area-based z_level. No
--           merge means no risk of z5-scale simplification distorting a
--           connector between two features into lake-width blob (the
--           Great Lakes / Niagara River case this redesign fixes).
--   z >= 12 (stroke on): tippecanoe's simplification tolerance is fine
--           enough here (--simplify-only-low-zooms) that unioning is
--           safe. Touching features get one extra row — the real
--           ST_Union of their connected cluster, fixed at z_level = 12 —
--           and their individual rows are marked capped = true, which
--           the filter in water_polygon.json uses to keep them out of
--           z12+ so only the merged row shows. Isolated features are
--           never capped.
--
-- Merging is deliberately confined to z>=12 rather than done everywhere:
-- a full dissolve (Erie + Niagara River + Ontario) simplified at z5
-- produces exactly the lake-width-channel artifact this redesign replaces.
-- Relying on tippecanoe's --coalesce instead of a real ST_Union was tried
-- and still left a seam — features simplify independently before
-- coalescing and can drift apart by a fraction of a pixel first.
--
-- Clustering (water.cluster_*, transient, dropped at the end): phase 0
-- finds adjacency pairs across ANY water type (a lake touching its inflow
-- river belongs in the same cluster); phase 1 clusters within each cell;
-- phase 2 resolves cross-cell clusters via relational connected components
-- (min-label propagation with pointer jumping, no geometry). The result
-- feeds the per-cluster ST_Union below.
--
-- Sharding: plain abs(osm_id) % 16 can land several of the very largest
-- features (millions of vertices) in the same shard by chance and stall
-- it behind its siblings. water.water_polygon_shard_override round-robins
-- the ~50 largest across shards explicitly; everything else hashes
-- normally via COALESCE(override.shard, abs(osm_id) % 16).
-- -----------------------------------------------------------------------------

BEGIN;
CREATE EXTENSION IF NOT EXISTS dblink;
DROP MATERIALIZED VIEW IF EXISTS export.water_polygon CASCADE;
DROP TABLE IF EXISTS water.water_polygon_parts CASCADE;
CREATE UNLOGGED TABLE water.water_polygon_parts (
    subclass text,
    geometry geometry(Polygon, 4326),
    z_level  int,
    capped   boolean NOT NULL DEFAULT false
);

DROP TABLE IF EXISTS water.water_polygon_shard_override CASCADE;
CREATE UNLOGGED TABLE water.water_polygon_shard_override AS
SELECT osm_id, (row_number() OVER (ORDER BY ST_NPoints(geometry) DESC) - 1) % 16 AS shard
FROM water.water_surface
WHERE subclass NOT IN ('bay', 'harbour', 'sea', 'strait')
  AND geometry IS NOT NULL
  AND NOT ST_IsEmpty(geometry)
ORDER BY ST_NPoints(geometry) DESC
LIMIT 50;

CREATE UNIQUE INDEX idx_water_polygon_shard_override_osm_id
    ON water.water_polygon_shard_override USING btree(osm_id);
COMMIT;

-- -----------------------------------------------------------------------------
-- water.cluster_* — connectivity clustering, used only to (a) mark touching
-- features as capped and (b) build one merged z12+ geometry per cluster.
-- Transient; dropped at the end of this section.
-- -----------------------------------------------------------------------------

BEGIN;
DROP TABLE IF EXISTS water.cluster_src CASCADE;
CREATE UNLOGGED TABLE water.cluster_src AS
-- Snap to a 0.000001 (~0.11m) grid once here, per-feature, so phase 0 can
-- use plain ST_Intersects (prepared-geometry speed) instead of ST_DWithin
-- (per-pair distance, ~40min vs a few minutes for phase 0). Not meant to
-- close real gaps — a z12 MVT tile's coordinate quantum (~2.4m) is ~20x
-- coarser than this anyway — just robustness against float ULP noise on
-- features OSM already says share a node. Same grid as the merge step's
-- ST_Union(geometry, 0.000001) below, so detection and execution agree.
--
-- ST_MakeValid only runs when ST_IsValid fails: input is already validated
-- (water.safe_simplify_geometry), and ST_ReducePrecision is documented
-- valid-in/valid-out, but collapsing vertices onto a grid point can in
-- principle still break validity, so this keeps the same conditional guard
-- safe_simplify_geometry uses rather than paying for unconditional
-- MakeValid on ~25M already-valid rows.
--
-- cell_x/cell_y are computed from the original (unsnapped) geometry —
-- free bbox-header reads, and only used for sharding/partitioning, not
-- correctness (phase 2 reconciles cross-cell clusters relationally).
--
-- OFFSET 0 blocks subquery pullup: without it Postgres inlines rp and
-- re-evaluates ST_ReducePrecision at every reference site (the CASE's
-- ST_IsValid test and its THEN branch) instead of once per row.
--
-- shard is materialized (not computed inline in phase 0/1's WHERE) so
-- both fan-outs filter on an indexed column instead of every worker
-- scanning the full table to evaluate the modulo and discard 15/16 of it.
SELECT
    osm_id,
    cell_x,
    cell_y,
    abs(cell_x * 92821 + cell_y) % 16                                     AS shard,
    CASE WHEN ST_IsValid(rp) THEN rp ELSE ST_MakeValid(rp, 'method=structure') END AS geometry
FROM (
    SELECT
        osm_id,
        floor((ST_XMin(geometry) + ST_XMax(geometry)) / 2.0)::int AS cell_x,
        floor((ST_YMin(geometry) + ST_YMax(geometry)) / 2.0)::int AS cell_y,
        ST_ReducePrecision(geometry, 0.000001) AS rp
    FROM water.water_surface
    WHERE subclass NOT IN ('bay', 'harbour', 'sea', 'strait')
      AND geometry IS NOT NULL
      AND NOT ST_IsEmpty(geometry)
    OFFSET 0
) pre
WHERE NOT ST_IsEmpty(rp);

-- osm_id (not a synthetic row_number(), which would serialize the write
-- through the leader) is already unique, so this CTAS stays parallel-insert-eligible.
CREATE INDEX idx_cluster_src_cell          ON water.cluster_src USING btree(cell_x, cell_y);
CREATE INDEX idx_cluster_src_shard         ON water.cluster_src USING btree(shard);
CREATE INDEX idx_cluster_src_geom          ON water.cluster_src USING gist(geometry);
CREATE UNIQUE INDEX idx_cluster_src_osm_id ON water.cluster_src USING btree(osm_id);
ANALYZE water.cluster_src;

DROP TABLE IF EXISTS water.cluster_pairs CASCADE;
CREATE UNLOGGED TABLE water.cluster_pairs (
    id_a bigint,
    id_b bigint
);
COMMIT;

-- Phase 0: every pair of features that touch, of ANY type (not grouped) — a
-- lake touching its inflow river belongs in the same cluster. Fanned out
-- over 16 dblink workers by shard: a.osm_id < b.osm_id ensures each pair is
-- emitted exactly once. The pair list doubles as the adjacency graph for
-- phase 2. Isolated features (the large majority) never enter phases 1-2.
DO $$
DECLARE
    nshards CONSTANT int := COALESCE(current_setting('abt.dissolve_shards', true)::int, 16);
    connstr CONSTANT text := format(
        'dbname=%s port=%s options=''-c work_mem=1GB -c synchronous_commit=off -c jit=off''',
        current_database(), current_setting('port'));
    i int;
    n int;
BEGIN
    FOR i IN 0 .. nshards - 1 LOOP
        PERFORM dblink_connect('wpair_w' || i, connstr);
        PERFORM dblink_send_query('wpair_w' || i, format($q$
            INSERT INTO water.cluster_pairs (id_a, id_b)
            SELECT a.osm_id, b.osm_id
            FROM water.cluster_src a
            JOIN water.cluster_src b
              ON a.osm_id < b.osm_id
             -- Plain ST_Intersects on the already-snapped geometry (see
             -- cluster_src's build comment) — prepared-geometry speed, no
             -- explicit && prefilter needed since ST_Intersects inlines
             -- the bbox check.
             AND ST_Intersects(a.geometry, b.geometry)
            WHERE a.shard = %s
        $q$, i));
    END LOOP;

    FOR i IN 0 .. nshards - 1 LOOP
        LOOP
            PERFORM * FROM dblink_get_result('wpair_w' || i) AS t(res text);
            GET DIAGNOSTICS n = ROW_COUNT;
            EXIT WHEN n = 0;
        END LOOP;
        PERFORM dblink_disconnect('wpair_w' || i);
    END LOOP;
EXCEPTION WHEN OTHERS THEN
    FOR i IN 0 .. nshards - 1 LOOP
        BEGIN
            PERFORM dblink_disconnect('wpair_w' || i);
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END LOOP;
    RAISE;
END;
$$;

BEGIN;
-- ids of features that touch anything, derived from the pair list.
DROP TABLE IF EXISTS water.cluster_adjacent CASCADE;
CREATE UNLOGGED TABLE water.cluster_adjacent AS
SELECT DISTINCT id
FROM (
    SELECT id_a AS id FROM water.cluster_pairs
    UNION ALL
    SELECT id_b FROM water.cluster_pairs
) u;

CREATE INDEX idx_cluster_adjacent_id ON water.cluster_adjacent USING btree(id);
ANALYZE water.cluster_adjacent;

CREATE INDEX idx_cluster_pairs_a ON water.cluster_pairs USING btree(id_a);
CREATE INDEX idx_cluster_pairs_b ON water.cluster_pairs USING btree(id_b);
ANALYZE water.cluster_pairs;

-- No geometry column: phase 2 is purely relational (cluster_pairs plus
-- this table's cell/local_cid), and the merge step re-reads geometry from
-- cluster_src by osm_id when needed — avoids storing it three times over
-- (cluster_src -> cluster_pass1 -> cluster_membership).
DROP TABLE IF EXISTS water.cluster_pass1 CASCADE;
CREATE UNLOGGED TABLE water.cluster_pass1 (
    osm_id      bigint,
    cell_x      int,
    cell_y      int,
    local_cid   int
);
COMMIT;

-- Phase 1: local (within-cell) clustering of touching features, fanned out
-- over 16 dblink workers. cluster_src/cluster_adjacent are committed above,
-- so the workers (separate sessions) can see them.
DO $$
DECLARE
    nshards CONSTANT int := COALESCE(current_setting('abt.dissolve_shards', true)::int, 16);
    connstr CONSTANT text := format(
        'dbname=%s port=%s options=''-c work_mem=1GB -c synchronous_commit=off -c jit=off''',
        current_database(), current_setting('port'));
    i int;
    n int;
BEGIN
    FOR i IN 0 .. nshards - 1 LOOP
        PERFORM dblink_connect('wclus_w' || i, connstr);
        PERFORM dblink_send_query('wclus_w' || i, format($q$
            INSERT INTO water.cluster_pass1
                (osm_id, cell_x, cell_y, local_cid)
            SELECT
                s.osm_id, s.cell_x, s.cell_y,
                ST_ClusterIntersectingWin(s.geometry) OVER (PARTITION BY s.cell_x, s.cell_y)
            FROM water.cluster_src s
            JOIN water.cluster_adjacent a ON a.id = s.osm_id
            WHERE s.shard = %s
        $q$, i));
    END LOOP;

    FOR i IN 0 .. nshards - 1 LOOP
        LOOP
            PERFORM * FROM dblink_get_result('wclus_w' || i) AS t(res text);
            GET DIAGNOSTICS n = ROW_COUNT;
            EXIT WHEN n = 0;
        END LOOP;
        PERFORM dblink_disconnect('wclus_w' || i);
    END LOOP;
EXCEPTION WHEN OTHERS THEN
    FOR i IN 0 .. nshards - 1 LOOP
        BEGIN
            PERFORM dblink_disconnect('wclus_w' || i);
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END LOOP;
    RAISE;
END;
$$;

-- Phase 2: merge local clusters split across a cell boundary — relationally,
-- from the phase-0 pair list, with no geometry involved: a pair whose two
-- features landed in different (cell, local_cid) clusters is an edge between
-- those clusters, and connected components over that small cluster-level
-- graph give the global cluster ids. Components are computed by min-label
-- propagation with pointer jumping; both updates strictly decrease labels,
-- so the loop terminates, and at the fixpoint every edge connects
-- equal-labelled nodes (each component uniformly carries its minimum
-- node_id).
BEGIN;
CREATE INDEX idx_cluster_pass1_osm_id ON water.cluster_pass1 USING btree(osm_id);
CREATE INDEX idx_cluster_pass1_key    ON water.cluster_pass1 USING btree(cell_x, cell_y, local_cid);
ANALYZE water.cluster_pass1;

-- One graph node per local cluster.
DROP TABLE IF EXISTS water.cluster_nodes CASCADE;
CREATE UNLOGGED TABLE water.cluster_nodes AS
SELECT
    row_number() OVER ()      AS node_id,
    cell_x, cell_y, local_cid
FROM water.cluster_pass1
GROUP BY cell_x, cell_y, local_cid;

CREATE UNIQUE INDEX idx_cluster_nodes_id  ON water.cluster_nodes USING btree(node_id);
CREATE UNIQUE INDEX idx_cluster_nodes_key ON water.cluster_nodes USING btree(cell_x, cell_y, local_cid);
ANALYZE water.cluster_nodes;

-- Edges between local clusters (pairs internal to one local cluster drop out).
DROP TABLE IF EXISTS water.cluster_edges CASCADE;
CREATE UNLOGGED TABLE water.cluster_edges AS
SELECT DISTINCT na.node_id AS node_a, nb.node_id AS node_b
FROM water.cluster_pairs pr
JOIN water.cluster_pass1 pa ON pa.osm_id = pr.id_a
JOIN water.cluster_pass1 pb ON pb.osm_id = pr.id_b
JOIN water.cluster_nodes na
  ON na.cell_x = pa.cell_x AND na.cell_y = pa.cell_y AND na.local_cid = pa.local_cid
JOIN water.cluster_nodes nb
  ON nb.cell_x = pb.cell_x AND nb.cell_y = pb.cell_y AND nb.local_cid = pb.local_cid
WHERE na.node_id <> nb.node_id;

CREATE INDEX idx_cluster_edges_a ON water.cluster_edges USING btree(node_a);
CREATE INDEX idx_cluster_edges_b ON water.cluster_edges USING btree(node_b);
ANALYZE water.cluster_edges;

DROP TABLE IF EXISTS water.cluster_labels CASCADE;
CREATE UNLOGGED TABLE water.cluster_labels AS
SELECT node_id, node_id AS label FROM water.cluster_nodes;

CREATE UNIQUE INDEX idx_cluster_labels_id    ON water.cluster_labels USING btree(node_id);
CREATE INDEX        idx_cluster_labels_label ON water.cluster_labels USING btree(label);
ANALYZE water.cluster_labels;

DO $$
DECLARE
    n_nbr bigint;
    n_jmp bigint;
BEGIN
    LOOP
        -- Adopt the smallest label reachable over one edge.
        UPDATE water.cluster_labels l
        SET label = b.min_nbr
        FROM (
            SELECT e.n AS node_id, MIN(nl.label) AS min_nbr
            FROM (
                SELECT node_a AS n, node_b AS m FROM water.cluster_edges
                UNION ALL
                SELECT node_b, node_a FROM water.cluster_edges
            ) e
            JOIN water.cluster_labels nl ON nl.node_id = e.m
            GROUP BY e.n
        ) b
        WHERE b.node_id = l.node_id
          AND b.min_nbr < l.label;
        GET DIAGNOSTICS n_nbr = ROW_COUNT;

        -- Pointer jumping: adopt the label of the node this label points to,
        -- collapsing chains so long thin components converge in ~log steps.
        UPDATE water.cluster_labels l
        SET label = p.label
        FROM water.cluster_labels p
        WHERE p.node_id = l.label
          AND p.label < l.label;
        GET DIAGNOSTICS n_jmp = ROW_COUNT;

        EXIT WHEN n_nbr = 0 AND n_jmp = 0;
    END LOOP;
END;
$$;

-- Map every touching feature to its final global cluster id. No geometry
-- here either — the merge step below re-reads it from cluster_src by osm_id.
DROP TABLE IF EXISTS water.cluster_membership CASCADE;
CREATE UNLOGGED TABLE water.cluster_membership AS
SELECT p.osm_id, l.label AS global_cid
FROM water.cluster_pass1 p
JOIN water.cluster_nodes n
  ON n.cell_x = p.cell_x AND n.cell_y = p.cell_y AND n.local_cid = p.local_cid
JOIN water.cluster_labels l ON l.node_id = n.node_id;

CREATE INDEX idx_cluster_membership_osm_id ON water.cluster_membership USING btree(osm_id);
CREATE INDEX idx_cluster_membership_cid    ON water.cluster_membership USING btree(global_cid);
ANALYZE water.cluster_membership;

-- cluster_src is dropped after the merge step below, which still needs it
-- to look up geometry by osm_id.
DROP TABLE water.cluster_pairs;
DROP TABLE water.cluster_adjacent;
DROP TABLE water.cluster_pass1;
DROP TABLE water.cluster_nodes;
DROP TABLE water.cluster_edges;
DROP TABLE water.cluster_labels;
COMMIT;

-- -----------------------------------------------------------------------------
-- Per-cluster ST_Union — the real merged geometry, fixed z_level = 12.
-- Scoped only to touching clusters (a small minority), fanned out over 16
-- dblink workers sharded by cluster id.
-- -----------------------------------------------------------------------------

DO $$
DECLARE
    nshards CONSTANT int := COALESCE(current_setting('abt.dissolve_shards', true)::int, 16);
    connstr CONSTANT text := format(
        'dbname=%s port=%s options=''-c work_mem=1GB -c synchronous_commit=off -c jit=off''',
        current_database(), current_setting('port'));
    i int;
    n int;
BEGIN
    FOR i IN 0 .. nshards - 1 LOOP
        PERFORM dblink_connect('wmerge_w' || i, connstr);
        PERFORM dblink_send_query('wmerge_w' || i, format($q$
            INSERT INTO water.water_polygon_parts (subclass, geometry, z_level, capped)
            SELECT 'water'::text, d.geom, 12, false
            FROM (
                -- gridSize 0.000001 matches the grid cluster_src is already
                -- snapped to, so this union doesn't re-round mid-pipeline.
                SELECT ST_Union(s.geometry, 0.000001) AS merged
                FROM water.cluster_membership cm
                JOIN water.cluster_src s USING (osm_id)
                WHERE abs(cm.global_cid) %% %s = %s
                GROUP BY cm.global_cid
            ) m
            -- No ST_Subdivide here (unlike the ocean layer, which needs it
            -- for 500k+ vertex, thousands-of-ring marsh geometry): inland
            -- water clusters are structurally simpler, HEAD's original
            -- dissolve fed whole merged networks to tippecanoe fine, and
            -- SQL-side subdivision was the actual source of the z12+ seam
            -- (--coalesce can't reliably re-join subdivided pieces at
            -- planet scale).
            CROSS JOIN LATERAL (
                SELECT (ST_Dump(ST_MakeValid(m.merged, 'method=structure'))).geom
            ) d(geom)
            WHERE ST_Dimension(d.geom) = 2
              AND NOT ST_IsEmpty(d.geom)
        $q$, nshards, i));
    END LOOP;

    FOR i IN 0 .. nshards - 1 LOOP
        LOOP
            PERFORM * FROM dblink_get_result('wmerge_w' || i) AS t(res text);
            GET DIAGNOSTICS n = ROW_COUNT;
            EXIT WHEN n = 0;
        END LOOP;
        PERFORM dblink_disconnect('wmerge_w' || i);
    END LOOP;
EXCEPTION WHEN OTHERS THEN
    FOR i IN 0 .. nshards - 1 LOOP
        BEGIN
            PERFORM dblink_disconnect('wmerge_w' || i);
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END LOOP;
    RAISE;
END;
$$;

BEGIN;
DROP TABLE water.cluster_src;
COMMIT;

-- Touching features (present in water.cluster_membership) are capped so
-- they never reach z12 — the merged row inserted above is what shows there.
DO $$
DECLARE
    nshards CONSTANT int := COALESCE(current_setting('abt.dissolve_shards', true)::int, 16);
    connstr CONSTANT text := format(
        'dbname=%s port=%s options=''-c work_mem=1GB -c synchronous_commit=off -c jit=off''',
        current_database(), current_setting('port'));
    i int;
    n int;
BEGIN
    FOR i IN 0 .. nshards - 1 LOOP
        PERFORM dblink_connect('wpoly_w' || i, connstr);
        PERFORM dblink_send_query('wpoly_w' || i, format($q$
            INSERT INTO water.water_polygon_parts (subclass, geometry, z_level, capped)
            SELECT
                'water'::text,
                d.geom,
                CASE WHEN t.grp = 'waterway' THEN GREATEST(t.z_area, 6) ELSE t.z_area END,
                t.is_member
            FROM (
                SELECT
                    grp,
                    src.geometry,
                    (cm.osm_id IS NOT NULL) AS is_member,
                    CASE
                        WHEN area_m2 >= POWER(zres(5), 2)  THEN 5
                        WHEN area_m2 >= POWER(zres(6), 2)  THEN 6
                        WHEN area_m2 >= POWER(zres(7), 2)  THEN 7
                        WHEN area_m2 >= POWER(zres(8), 2)  THEN 8
                        WHEN area_m2 >= POWER(zres(9), 2)  THEN 9
                        WHEN area_m2 >= POWER(zres(10), 2) THEN 10
                        WHEN area_m2 >= POWER(zres(11), 2) THEN 11
                        ELSE 12
                    END AS z_area
                FROM (
                    SELECT
                        ws.osm_id,
                        CASE
                            WHEN water_type IN (
                                'river', 'canal', 'stream', 'ditch', 'drain', 'creek', 'brook',
                                'bayou', 'rapids', 'tidal', 'estuary', 'falls', 'spillway',
                                'channel', 'canoe_pass', 'fish_pass', 'connector'
                            ) THEN 'waterway'
                            ELSE 'water'
                        END AS grp,
                        geometry,
                        ST_Area(geometry::geography, false) AS area_m2
                    FROM water.water_surface ws
                    LEFT JOIN water.water_polygon_shard_override o USING (osm_id)
                    WHERE subclass NOT IN ('bay', 'harbour', 'sea', 'strait')
                      AND COALESCE(o.shard, abs(ws.osm_id) %% %s) = %s
                      AND geometry IS NOT NULL
                      AND NOT ST_IsEmpty(geometry)
                ) src
                LEFT JOIN water.cluster_membership cm ON cm.osm_id = src.osm_id
            ) t
            CROSS JOIN LATERAL (
                SELECT geom FROM ST_Subdivide(t.geometry, 1024) AS geom
                WHERE ST_NPoints(t.geometry) > 1024
                UNION ALL
                SELECT t.geometry
                WHERE ST_NPoints(t.geometry) <= 1024
            ) s(geom)
            -- ST_MakeValid can hand back a MultiPolygon/GeometryCollection
            -- even from Polygon input, so dump to guarantee single Polygon
            -- rows for water_polygon_parts' typed column.
            CROSS JOIN LATERAL (
                SELECT (ST_Dump(ST_MakeValid(s.geom, 'method=structure'))).geom
            ) d(geom)
            WHERE ST_Dimension(d.geom) = 2
              AND NOT ST_IsEmpty(d.geom)
        $q$, nshards, i));
    END LOOP;

    FOR i IN 0 .. nshards - 1 LOOP
        LOOP
            PERFORM * FROM dblink_get_result('wpoly_w' || i) AS t(res text);
            GET DIAGNOSTICS n = ROW_COUNT;
            EXIT WHEN n = 0;
        END LOOP;
        PERFORM dblink_disconnect('wpoly_w' || i);
    END LOOP;
EXCEPTION WHEN OTHERS THEN
    FOR i IN 0 .. nshards - 1 LOOP
        BEGIN
            PERFORM dblink_disconnect('wpoly_w' || i);
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END LOOP;
    RAISE;
END;
$$;

BEGIN;
CREATE MATERIALIZED VIEW export.water_polygon AS

SELECT
    'lake'::text                                                    AS subclass,
    ST_MakeValid(
        (ST_Dump(geometry)).geom::geometry(Polygon, 4326),
        'method=structure'
    )                                                               AS geometry,
    1                                                               AS z_level,
    false                                                           AS capped
FROM aux_data.ne_50m_lakes
WHERE geometry IS NOT NULL
  AND NOT ST_IsEmpty(geometry)

UNION ALL

SELECT subclass, geometry, z_level, capped
FROM water.water_polygon_parts;

DROP TABLE water.water_polygon_shard_override;
DROP TABLE water.cluster_membership;

CREATE INDEX idx_water_geometry ON export.water_polygon USING gist(geometry);
CREATE INDEX idx_water_subclass ON export.water_polygon USING btree(subclass);
CREATE INDEX idx_water_z_level  ON export.water_polygon USING btree(z_level);
CREATE INDEX idx_water_capped   ON export.water_polygon USING btree(capped);
COMMIT;
