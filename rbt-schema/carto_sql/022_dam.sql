-- =============================================================================
-- LAYER: Dam
-- Schema:        export
-- Sources:       osm.osm_waterway_linestring
--                osm.osm_water_polygon
--                osm.osm_water_point
--                osm.osm_highway_linestring (surface enrichment)
--
-- Build order matters: dam_polygon is built first because dam_line filters
-- out linestring echoes of area-mapped dams against it.
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
CREATE SCHEMA IF NOT EXISTS dam;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.dam_polygon — dam and weir polygons
--
-- surface: hard/loose bucket from the feature's own tags; when those are
-- absent, inferred from surfaced highways running along the dam crest.
-- Crest test: per hard/loose bucket, total intersection length of surfaced
-- highways must reach 25% of the polygon perimeter (≈ half the major axis) —
-- a perpendicular crossing only contributes the dam's width and fails.
-- surface_src ('tag'/'highway'/NULL) records provenance; it is not in the
-- tile schema (export/dam_polygon.json lists fields explicitly).
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.dam_polygon CASCADE;
CREATE MATERIALIZED VIEW export.dam_polygon AS
WITH src AS (
    SELECT
        NULLIF(name, '')                                                AS name,
        NULLIF(name_en, '')                                             AS name_en,
        subclass                                                        AS fclass,
        CASE
            WHEN LOWER(COALESCE(NULLIF(tags->'surface',''), NULLIF(tags->'material',''), NULLIF(tags->'dam:type',''))) IN (
                'asphalt', 'cement', 'cobblestone', 'concrete', 'concrete:lanes', 'concrete:plates',
                'dam', 'metal', 'metal_grid', 'paved', 'paving_stones', 'pebblestone', 'rock',
                'sett', 'stepping_stones', 'stone', 'unhewn_cobblestone', 'wood',
                'concrete_faced', 'roller_compacted_concrete', 'masonry', 'arch'
            ) THEN 'hard'
            WHEN LOWER(COALESCE(NULLIF(tags->'surface',''), NULLIF(tags->'material',''), NULLIF(tags->'dam:type',''))) IN (
                'compacted', 'dirt', 'earth', 'fine_gravel', 'grass', 'gravel', 'ground',
                'mud', 'sand', 'unpaved',
                'earth_fill', 'rock_fill', 'embankment', 'earthen'
            ) THEN 'loose'
            ELSE NULL
        END                                                             AS tag_surface,
        ST_Area(ST_Transform(geometry, 3857))::real                     AS area,
        geometry
    FROM osm.osm_water_polygon
    WHERE subclass IN ('dam', 'weir', 'sluice_gate', 'flood_gate')
)
SELECT
    s.name,
    s.name_en,
    s.fclass,
    COALESCE(
        s.tag_surface,
        CASE WHEN hw.total >= 0.25 * ST_Perimeter(s.geometry) THEN hw.bucket END
    )                                                                   AS surface,
    CASE
        WHEN s.tag_surface IS NOT NULL                                THEN 'tag'
        WHEN hw.total >= 0.25 * ST_Perimeter(s.geometry)              THEN 'highway'
    END                                                                 AS surface_src,
    s.area,
    s.geometry
FROM src s
LEFT JOIN LATERAL (
    -- aggregate by bucket across all intersecting surfaced highways: OSM ways
    -- are heavily split, so no single fragment can be required to span the
    -- crest on its own
    SELECT x.bucket, sum(x.seg_len) AS total
    FROM (
        SELECT
            CASE
                WHEN lower(h.surface) ~ '(asphalt|asphal|asfalt|tarmac|concrete|cement|cobblestone|sett|paving_stone|brick|block|metal|steel|wood|boardwalk|chipseal|tiles|flagstone|bitum|interlock|paver|tartan|unhewn_cobblestone|pebblestone|\mpaved\M)' THEN 'hard'
                WHEN lower(h.surface) ~ '(unpaved|dirt|gravel|sand|earth|mud|grass|ground|clay|soil|compacted|fine_gravel|ice|snow|shell|rock|stone)' THEN 'loose'
            END                                                     AS bucket,
            ST_Length(ST_Intersection(h.geometry, s.geometry))      AS seg_len
        FROM osm.osm_highway_linestring h
        WHERE s.tag_surface IS NULL
          AND h.geometry && s.geometry
          AND NULLIF(h.surface, '') IS NOT NULL
          AND ST_Intersects(h.geometry, s.geometry)
    ) x
    WHERE x.bucket IS NOT NULL
    GROUP BY x.bucket
    ORDER BY total DESC
    LIMIT 1
) hw ON true;

CREATE INDEX idx_dam_surface_geometry ON export.dam_polygon USING gist(geometry);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.dam_line — dam and weir linestrings
--
-- Curves that are >=60% coincident with a dam polygon are dropped: they are
-- the linestring echo of an area-mapped dam (waterway=dam ways land in both
-- source tables), which otherwise renders a redundant outline.
-- Surface enrichment mirrors dam_polygon, using a 20 m corridor around the
-- line; the winning bucket must cover at least half the line's length.
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.dam_line CASCADE;
CREATE MATERIALIZED VIEW export.dam_line AS
WITH src AS (
    SELECT
        NULLIF(name, '')                                                AS name,
        NULLIF(name_en, '')                                             AS name_en,
        subclass                                                        AS fclass,
        CASE
            WHEN LOWER(COALESCE(NULLIF(tags->'surface',''), NULLIF(tags->'material',''), NULLIF(tags->'dam:type',''))) IN (
                'asphalt', 'cement', 'cobblestone', 'concrete', 'concrete:lanes', 'concrete:plates',
                'dam', 'metal', 'metal_grid', 'paved', 'paving_stones', 'pebblestone', 'rock',
                'sett', 'stepping_stones', 'stone', 'unhewn_cobblestone', 'wood',
                'concrete_faced', 'roller_compacted_concrete', 'masonry', 'arch'
            ) THEN 'hard'
            WHEN LOWER(COALESCE(NULLIF(tags->'surface',''), NULLIF(tags->'material',''), NULLIF(tags->'dam:type',''))) IN (
                'compacted', 'dirt', 'earth', 'fine_gravel', 'grass', 'gravel', 'ground',
                'mud', 'sand', 'unpaved',
                'earth_fill', 'rock_fill', 'embankment', 'earthen'
            ) THEN 'loose'
            ELSE NULL
        END                                                             AS tag_surface,
        ST_Length(geometry)                                             AS length,
        geometry
    FROM osm.osm_waterway_linestring
    -- Exact match instead of ILIKE '%..%' — avoids full sequential scan on large table.
    -- OSM subclass values for dams/weirs are always exact lowercase strings from imposm mapping.
    WHERE subclass IN ('dam', 'weir', 'sluice_gate', 'flood_gate')
),
kept AS (
    SELECT s.*
    FROM src s
    WHERE s.length = 0
       OR COALESCE((
            SELECT sum(ST_Length(ST_Intersection(s.geometry, p.geometry)))
            FROM export.dam_polygon p
            WHERE s.geometry && p.geometry
              AND ST_Intersects(s.geometry, p.geometry)
          ), 0) / s.length <= 0.6
)
SELECT
    k.name,
    k.name_en,
    k.fclass,
    COALESCE(
        k.tag_surface,
        CASE WHEN hw.total >= 0.5 * k.length THEN hw.bucket END
    )                                                                   AS surface,
    CASE
        WHEN k.tag_surface IS NOT NULL                                THEN 'tag'
        WHEN hw.total >= 0.5 * k.length                               THEN 'highway'
    END                                                                 AS surface_src,
    k.length,
    k.geometry
FROM kept k
CROSS JOIN LATERAL (
    -- corridor is NULL when the dam has its own surface tag, which empties
    -- the highway lateral below without computing the geodesic buffer
    SELECT CASE
        WHEN k.tag_surface IS NULL
        THEN ST_Buffer(k.geometry::geography, 20)::geometry
    END AS geom
) corridor
LEFT JOIN LATERAL (
    SELECT x.bucket, sum(x.seg_len) AS total
    FROM (
        SELECT
            CASE
                WHEN lower(h.surface) ~ '(asphalt|asphal|asfalt|tarmac|concrete|cement|cobblestone|sett|paving_stone|brick|block|metal|steel|wood|boardwalk|chipseal|tiles|flagstone|bitum|interlock|paver|tartan|unhewn_cobblestone|pebblestone|\mpaved\M)' THEN 'hard'
                WHEN lower(h.surface) ~ '(unpaved|dirt|gravel|sand|earth|mud|grass|ground|clay|soil|compacted|fine_gravel|ice|snow|shell|rock|stone)' THEN 'loose'
            END                                                     AS bucket,
            ST_Length(ST_Intersection(h.geometry, corridor.geom))   AS seg_len
        FROM osm.osm_highway_linestring h
        WHERE h.geometry && corridor.geom
          AND NULLIF(h.surface, '') IS NOT NULL
          AND ST_Intersects(h.geometry, corridor.geom)
    ) x
    WHERE x.bucket IS NOT NULL
    GROUP BY x.bucket
    ORDER BY total DESC
    LIMIT 1
) hw ON true;

CREATE INDEX idx_dam_curve_geometry ON export.dam_line USING gist(geometry);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.dam_label — label points for dam and weir features
--
-- Labels exist only for named features: the supplemental branches skip
-- unnamed polygons/lines rather than synthesizing 'Unnamed Dam' placeholders.
-- -----------------------------------------------------------------------------
BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.dam_label CASCADE;
DROP TABLE IF EXISTS dam.label_tmp_surface_points;
DROP TABLE IF EXISTS dam.label_tmp_point_labels;
COMMIT;

-- Named dam points, staged into an indexed table so the dam_line
-- deduplication ST_Intersects check probes a GIST index rather than a
-- materialized, unindexed CTE.
-- Water checks exclude dam subclasses so water_intersect means "touches
-- actual water", not "touches itself or another dam feature".
-- EXISTS pairs short-circuit: the expensive waterway ST_DWithin probe only
-- runs when the water-polygon probe missed.
BEGIN;
CREATE TABLE dam.label_tmp_point_labels AS
SELECT
    wl.id                                                               AS fid,
    NULLIF(wl.name, '')                                                 AS name,
    NULLIF(wl.name_en, '')                                              AS name_en,
    wl.subclass                                                         AS fclass,
    CASE
        WHEN LOWER(wl.tags -> 'surface') IN ('asphalt', 'cement', 'concrete', 'rock', 'stone', 'wood') THEN 'hard'
        WHEN LOWER(wl.tags -> 'surface') IN ('dirt', 'earth', 'grass', 'gravel', 'mud', 'sand')        THEN 'loose'
        ELSE NULL
    END                                                                 AS surface,
    CASE WHEN EXISTS (
             SELECT 1 FROM osm.osm_water_polygon w
             WHERE ST_Intersects(wl.geometry, w.geometry)
               AND w.subclass NOT IN ('dam', 'weir', 'sluice_gate', 'flood_gate')
         )
         OR EXISTS (
             SELECT 1 FROM osm.osm_waterway_linestring ww
             WHERE ST_DWithin(wl.geometry, ww.geometry, 0.005)
               AND ww.subclass NOT IN ('dam', 'weir', 'sluice_gate', 'flood_gate')
         )
         THEN 'Y' ELSE 'N' END                                          AS water_intersect,
    CASE WHEN EXISTS (
             SELECT 1 FROM export.dam_polygon ds
             WHERE ST_Intersects(wl.geometry, ds.geometry)
         )
         OR EXISTS (
             SELECT 1 FROM export.dam_line dc
             WHERE ST_Intersects(wl.geometry, dc.geometry)
         )
         THEN 'Y' ELSE 'N' END                                          AS dam_srf_crv_intersect,
    wl.geometry
FROM osm.osm_water_point wl
WHERE wl.subclass IN ('dam', 'weir', 'sluice_gate', 'flood_gate')
  AND NULLIF(wl.name, '') IS NOT NULL;

CREATE INDEX idx_dam_label_tmp_point_labels ON dam.label_tmp_point_labels USING gist(geometry);
ANALYZE dam.label_tmp_point_labels;
COMMIT;

-- Supplemental surface points (named polygons only), staged so the curve
-- deduplication ST_DWithin check runs against an indexed table rather than
-- an unindexed CTE
BEGIN;
CREATE TABLE dam.label_tmp_surface_points AS
SELECT
    NULL::integer                                                       AS fid,
    ds.name,
    ds.name_en,
    ds.fclass,
    ds.surface,
    CASE WHEN EXISTS (
             SELECT 1 FROM osm.osm_water_polygon w
             WHERE ST_Intersects(ds.geometry, w.geometry)
               AND w.subclass NOT IN ('dam', 'weir', 'sluice_gate', 'flood_gate')
         )
         OR EXISTS (
             SELECT 1 FROM osm.osm_waterway_linestring ww
             WHERE ST_DWithin(ds.geometry, ww.geometry, 0.005)
               AND ww.subclass NOT IN ('dam', 'weir', 'sluice_gate', 'flood_gate')
         )
         THEN 'Y' ELSE 'N' END                                          AS water_intersect,
    'Y'                                                                 AS dam_srf_crv_intersect,
    ST_PointOnSurface(ds.geometry)::geometry(Point, 4326)               AS geometry
FROM export.dam_polygon ds
WHERE ds.name IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM osm.osm_water_point ol
    WHERE ol.subclass IN ('dam', 'weir', 'sluice_gate', 'flood_gate')
      AND ST_Intersects(ds.geometry, ol.geometry)
);

CREATE INDEX idx_dam_label_tmp_surface_points ON dam.label_tmp_surface_points USING gist(geometry);
ANALYZE dam.label_tmp_surface_points;
COMMIT;

BEGIN;
CREATE MATERIALIZED VIEW export.dam_label AS
WITH curve_midpoints AS (
    SELECT
        dc.name,
        dc.name_en,
        dc.fclass,
        dc.surface,
        dc.geometry                                                     AS line_geometry,
        ST_LineInterpolatePoint(dc.geometry, 0.5)                       AS midpoint
    FROM export.dam_line dc
    WHERE dc.name IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM dam.label_tmp_point_labels ol
        WHERE ST_Intersects(dc.geometry, ol.geometry)
    )
),
supplemental_curve_points AS (
    SELECT
        NULL::integer                                                   AS fid,
        cm.name,
        cm.name_en,
        cm.fclass,
        cm.surface,
        CASE WHEN EXISTS (
                 SELECT 1 FROM osm.osm_water_polygon w
                 WHERE ST_Intersects(cm.line_geometry, w.geometry)
                   AND w.subclass NOT IN ('dam', 'weir', 'sluice_gate', 'flood_gate')
             )
             OR EXISTS (
                 SELECT 1 FROM osm.osm_waterway_linestring ww
                 WHERE ST_DWithin(cm.line_geometry, ww.geometry, 0.005)
                   AND ww.subclass NOT IN ('dam', 'weir', 'sluice_gate', 'flood_gate')
             )
             THEN 'Y' ELSE 'N' END                                      AS water_intersect,
        'Y'                                                             AS dam_srf_crv_intersect,
        cm.midpoint                                                     AS geometry
    FROM curve_midpoints cm
    WHERE NOT EXISTS (
        SELECT 1 FROM dam.label_tmp_surface_points ssp
        WHERE ST_DWithin(cm.midpoint, ssp.geometry, 0.0001)
    )
)
SELECT fid, name, name_en, fclass, surface, water_intersect, dam_srf_crv_intersect, geometry
FROM dam.label_tmp_point_labels
UNION ALL
SELECT fid, name, name_en, fclass, surface, water_intersect, dam_srf_crv_intersect, geometry
FROM dam.label_tmp_surface_points
UNION ALL
SELECT fid, name, name_en, fclass, surface, water_intersect, dam_srf_crv_intersect, geometry
FROM supplemental_curve_points;

CREATE INDEX idx_dam_label_geometry ON export.dam_label USING gist(geometry);
COMMIT;
