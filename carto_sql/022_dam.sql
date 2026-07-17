-- =============================================================================
-- LAYER: Dam
-- Schema:        export
-- Sources:       osm.osm_waterway_linestring
--                osm.osm_water_polygon
--                osm.osm_water_point
-- =============================================================================


-- -----------------------------------------------------------------------------
-- SCHEMA
-- -----------------------------------------------------------------------------

BEGIN;
CREATE SCHEMA IF NOT EXISTS dam;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.dam_line — dam and weir linestrings
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.dam_line CASCADE;
CREATE MATERIALIZED VIEW export.dam_line AS
SELECT
    NULLIF(name, '')                                                    AS name,
    NULLIF(name_en, '')                                                 AS name_en,
    subclass                                                            AS fclass,
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
    END                                                                 AS surface,
    ST_Length(geometry)                                                 AS length,
    geometry
FROM osm.osm_waterway_linestring
-- Exact match instead of ILIKE '%..%' — avoids full sequential scan on large table.
-- OSM subclass values for dams/weirs are always exact lowercase strings from imposm mapping.
WHERE subclass IN ('dam', 'weir', 'sluice_gate', 'flood_gate');

CREATE INDEX idx_dam_curve_geometry ON export.dam_line USING gist(geometry);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.dam_polygon — dam and weir polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.dam_polygon CASCADE;
CREATE MATERIALIZED VIEW export.dam_polygon AS
SELECT
    NULLIF(name, '')                                                    AS name,
    NULLIF(name_en, '')                                                 AS name_en,
    subclass                                                            AS fclass,
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
    END                                                                 AS surface,
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area,
    geometry
FROM osm.osm_water_polygon
WHERE subclass IN ('dam', 'weir', 'sluice_gate', 'flood_gate');

CREATE INDEX idx_dam_surface_geometry ON export.dam_polygon USING gist(geometry);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.dam_label — label points for dam and weir features
-- -----------------------------------------------------------------------------
BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.dam_label CASCADE;
DROP TABLE IF EXISTS dam.label_tmp_surface_points;
COMMIT;

-- Materialize supplemental surface points into a staging table so the curve
-- deduplication ST_DWithin check runs against an indexed table rather than an unindexed CTE
BEGIN;
CREATE TABLE dam.label_tmp_surface_points AS
SELECT
    NULL::integer                                                       AS fid,
    COALESCE(ds.name, 'Unnamed Dam')                                    AS name,
    COALESCE(ds.name_en, 'Unnamed Dam')                                 AS name_en,
    ds.fclass,
    ds.surface,
    CASE WHEN wp.hit IS NOT NULL OR wl.hit IS NOT NULL THEN 'Y' ELSE 'N' END
                                                                        AS water_intersect,
    'Y'                                                                 AS dam_srf_crv_intersect,
    ST_PointOnSurface(ds.geometry)::geometry(Point, 4326)               AS geometry
FROM export.dam_polygon ds
LEFT JOIN LATERAL (
    SELECT 1 AS hit FROM osm.osm_water_polygon w
    WHERE ST_Intersects(ds.geometry, w.geometry) LIMIT 1
) wp ON true
LEFT JOIN LATERAL (
    SELECT 1 AS hit FROM osm.osm_waterway_linestring ww
    WHERE ST_DWithin(ds.geometry, ww.geometry, 0.005) LIMIT 1
) wl ON true
WHERE NOT EXISTS (
    SELECT 1 FROM osm.osm_water_point ol
    WHERE ol.subclass IN ('dam', 'weir', 'sluice_gate', 'flood_gate')
      AND ST_Intersects(ds.geometry, ol.geometry)
);

CREATE INDEX idx_dam_label_tmp_surface_points ON dam.label_tmp_surface_points USING gist(geometry);
COMMIT;

BEGIN;
CREATE MATERIALIZED VIEW export.dam_label AS
WITH original_labels AS (
    SELECT
        wl.id                                                           AS fid,
        NULLIF(wl.name, '')                                             AS name,
        NULLIF(wl.name_en, '')                                          AS name_en,
        wl.subclass                                                     AS fclass,
        CASE
            WHEN LOWER(wl.tags -> 'surface') IN ('asphalt', 'cement', 'concrete', 'rock', 'stone', 'wood') THEN 'hard'
            WHEN LOWER(wl.tags -> 'surface') IN ('dirt', 'earth', 'grass', 'gravel', 'mud', 'sand')        THEN 'loose'
            ELSE NULL
        END                                                             AS surface,
        CASE WHEN wp.hit IS NOT NULL OR wl2.hit IS NOT NULL THEN 'Y' ELSE 'N' END
                                                                        AS water_intersect,
        CASE WHEN dp.hit IS NOT NULL OR dl.hit IS NOT NULL THEN 'Y' ELSE 'N' END
                                                                        AS dam_srf_crv_intersect,
        wl.geometry
    FROM osm.osm_water_point wl
    LEFT JOIN LATERAL (
        SELECT 1 AS hit FROM osm.osm_water_polygon w
        WHERE ST_Intersects(wl.geometry, w.geometry) LIMIT 1
    ) wp  ON true
    LEFT JOIN LATERAL (
        SELECT 1 AS hit FROM osm.osm_waterway_linestring ww
        WHERE ST_DWithin(wl.geometry, ww.geometry, 0.005) LIMIT 1
    ) wl2 ON true
    LEFT JOIN LATERAL (
        SELECT 1 AS hit FROM export.dam_polygon ds
        WHERE ST_Intersects(wl.geometry, ds.geometry) LIMIT 1
    ) dp  ON true
    LEFT JOIN LATERAL (
        SELECT 1 AS hit FROM export.dam_line dc
        WHERE ST_Intersects(wl.geometry, dc.geometry) LIMIT 1
    ) dl  ON true
    WHERE wl.subclass IN ('dam', 'weir', 'sluice_gate', 'flood_gate')
      AND NULLIF(wl.name, '') IS NOT NULL
),
curve_midpoints AS (
    SELECT
        dc.name,
        dc.name_en,
        dc.fclass,
        dc.surface,
        dc.geometry                                                     AS line_geometry,
        ST_LineInterpolatePoint(dc.geometry, 0.5)                       AS midpoint
    FROM export.dam_line dc
    WHERE NOT EXISTS (
        SELECT 1 FROM original_labels ol
        WHERE ST_Intersects(dc.geometry, ol.geometry)
    )
),
supplemental_curve_points AS (
    SELECT
        NULL::integer                                                   AS fid,
        COALESCE(cm.name, 'Unnamed Dam')                                AS name,
        COALESCE(cm.name_en, 'Unnamed Dam')                             AS name_en,
        cm.fclass,
        cm.surface,
        CASE WHEN wp.hit IS NOT NULL OR wl.hit IS NOT NULL THEN 'Y' ELSE 'N' END
                                                                        AS water_intersect,
        'Y'                                                             AS dam_srf_crv_intersect,
        cm.midpoint                                                     AS geometry
    FROM curve_midpoints cm
    LEFT JOIN LATERAL (
        SELECT 1 AS hit FROM osm.osm_water_polygon w
        WHERE ST_Intersects(cm.line_geometry, w.geometry) LIMIT 1
    ) wp ON true
    LEFT JOIN LATERAL (
        SELECT 1 AS hit FROM osm.osm_waterway_linestring ww
        WHERE ST_DWithin(cm.line_geometry, ww.geometry, 0.005) LIMIT 1
    ) wl ON true
    WHERE NOT EXISTS (
        SELECT 1 FROM dam.label_tmp_surface_points ssp
        WHERE ST_DWithin(cm.midpoint, ssp.geometry, 0.0001)
    )
)
SELECT * FROM original_labels
UNION ALL
SELECT * FROM dam.label_tmp_surface_points
UNION ALL
SELECT * FROM supplemental_curve_points;

CREATE INDEX idx_dam_label_geometry ON export.dam_label USING gist(geometry);
COMMIT;
