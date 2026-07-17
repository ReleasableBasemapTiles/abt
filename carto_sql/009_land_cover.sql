-- =============================================================================
-- LAYER: Land Cover
-- Schema:        export
-- Intermediates: landcover.preprocessed
-- Sources:       osm.osm_landcover_polygon
-- =============================================================================


-- -----------------------------------------------------------------------------
-- SCHEMA
-- -----------------------------------------------------------------------------

BEGIN;
CREATE SCHEMA IF NOT EXISTS landcover;
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
-- export.landcover_polygon — simplification cascade z4–z13
--
-- Each row represents a feature at ONE specific zoom level, simplified
-- appropriately for that zoom. z_level = exact zoom, not minimum zoom.
--
-- Cascade builds top-down: each zN_simplified derives from zN+1_simplified,
-- applying progressively coarser VW simplification and dropping features
-- too small for the next zoom level.
--
-- Forest/wood is clustered with ST_ClusterDBSCAN to merge adjacent patches:
--   z7–z9   cluster all forest/wood
--   z10–z13 cluster only small forest/wood (vertex_count < 300)
--
-- Subclass filtering per zoom:
--   z4–z5   coastal only  (sand, beach, dune, glacier, bare_rock, scree, shoal)
--   z6      above + all wetland types
--   z7–z9   above + forest, wood
--   z10–z13 all subclasses
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.landcover_polygon CASCADE;
CREATE MATERIALIZED VIEW export.landcover_polygon AS
WITH

z13_source AS (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, vertex_count,
           ST_MakeValid(
               ST_SnapToGrid(geometry, 0.001)
           )                                                            AS geometry
    FROM landcover.preprocessed
),
z12_simplified AS (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, vertex_count,
           ST_MakeValid(
               ST_SnapToGrid(ST_SimplifyVW(geometry, power(zres(12), 2)), 0.001)
           )                                                            AS geometry
    FROM z13_source
    WHERE ST_Area(geometry) > power(zres(11), 2)
),
z11_simplified AS (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, vertex_count,
           ST_MakeValid(
               ST_SnapToGrid(ST_SimplifyVW(geometry, power(zres(11), 2)), 0.001)
           )                                                            AS geometry
    FROM z12_simplified
    WHERE ST_Area(geometry) > power(zres(10), 2)
),
z10_simplified AS (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, vertex_count,
           ST_MakeValid(
               ST_SnapToGrid(ST_SimplifyVW(geometry, power(zres(10), 2)), 0.001)
           )                                                            AS geometry
    FROM z11_simplified
    WHERE ST_Area(geometry) > power(zres(9), 2)
),
z9_simplified AS (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, vertex_count,
           ST_MakeValid(
               ST_SnapToGrid(ST_SimplifyVW(geometry, power(zres(9), 2)), 0.001)
           )                                                            AS geometry
    FROM z10_simplified
    WHERE ST_Area(geometry) > power(zres(8), 2)
),
z8_simplified AS (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, vertex_count,
           ST_MakeValid(
               ST_SnapToGrid(ST_SimplifyVW(geometry, power(zres(8), 2)), 0.001)
           )                                                            AS geometry
    FROM z9_simplified
    WHERE ST_Area(geometry) > power(zres(7), 2)
),
z7_simplified AS (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, vertex_count,
           ST_MakeValid(
               ST_SnapToGrid(ST_SimplifyVW(geometry, power(zres(7), 2)), 0.001)
           )                                                            AS geometry
    FROM z8_simplified
    WHERE ST_Area(geometry) > power(zres(6), 2)
),
z6_simplified AS (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, vertex_count,
           ST_MakeValid(
               ST_SnapToGrid(ST_SimplifyVW(geometry, power(zres(6), 2)), 0.001)
           )                                                            AS geometry
    FROM z7_simplified
    WHERE ST_Area(geometry) > power(zres(5), 2)
),
z5_simplified AS (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, vertex_count,
           ST_MakeValid(
               ST_SnapToGrid(ST_SimplifyVW(geometry, power(zres(5), 2)), 0.001)
           )                                                            AS geometry
    FROM z6_simplified
    WHERE ST_Area(geometry) > power(zres(4), 2)
),
z4_simplified AS (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, vertex_count,
           ST_MakeValid(
               ST_SnapToGrid(ST_SimplifyVW(geometry, power(zres(4), 2)), 0.001)
           )                                                            AS geometry
    FROM z5_simplified
    WHERE ST_Area(geometry) > power(zres(3), 2)
),

-- ── Output CTEs: cluster forest/wood, apply subclass filters ─────────────────

-- z13: all subclasses — cluster small forest/wood
z13 AS (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, 13 AS z_level,
           ST_Transform(ST_MakeValid((ST_Dump(ST_Union(geometry))).geom), 4326) AS geometry
    FROM (
        SELECT subclass, leaf_type, leaf_cycle, intermittent,
               ST_ClusterDBSCAN(geometry, eps := 0, minpoints := 1) OVER (PARTITION BY subclass) AS cid,
               geometry
        FROM z13_source
        WHERE vertex_count < 300 AND subclass IN ('wood', 'forest')
    ) c
    GROUP BY subclass, leaf_type, leaf_cycle, intermittent, cid
    UNION ALL
    SELECT subclass, leaf_type, leaf_cycle, intermittent, 13 AS z_level,
           ST_Transform(geometry, 4326) AS geometry
    FROM z13_source
    WHERE (vertex_count >= 300 AND subclass IN ('wood', 'forest'))
       OR subclass NOT IN ('wood', 'forest')
),

-- z12: all subclasses — cluster small forest/wood
z12 AS (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, 12 AS z_level,
           ST_Transform(ST_MakeValid((ST_Dump(ST_Union(geometry))).geom), 4326) AS geometry
    FROM (
        SELECT subclass, leaf_type, leaf_cycle, intermittent,
               ST_ClusterDBSCAN(geometry, eps := 0, minpoints := 1) OVER (PARTITION BY subclass) AS cid,
               geometry
        FROM z12_simplified
        WHERE vertex_count < 300 AND subclass IN ('wood', 'forest')
    ) c
    GROUP BY subclass, leaf_type, leaf_cycle, intermittent, cid
    UNION ALL
    SELECT subclass, leaf_type, leaf_cycle, intermittent, 12 AS z_level,
           ST_Transform(geometry, 4326) AS geometry
    FROM z12_simplified
    WHERE (vertex_count >= 300 AND subclass IN ('wood', 'forest'))
       OR subclass NOT IN ('wood', 'forest')
),

-- z11: all subclasses — cluster small forest/wood
z11 AS (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, 11 AS z_level,
           ST_Transform(ST_MakeValid((ST_Dump(ST_Union(geometry))).geom), 4326) AS geometry
    FROM (
        SELECT subclass, leaf_type, leaf_cycle, intermittent,
               ST_ClusterDBSCAN(geometry, eps := 0, minpoints := 1) OVER (PARTITION BY subclass) AS cid,
               geometry
        FROM z11_simplified
        WHERE vertex_count < 300 AND subclass IN ('wood', 'forest')
    ) c
    GROUP BY subclass, leaf_type, leaf_cycle, intermittent, cid
    UNION ALL
    SELECT subclass, leaf_type, leaf_cycle, intermittent, 11 AS z_level,
           ST_Transform(geometry, 4326) AS geometry
    FROM z11_simplified
    WHERE (vertex_count >= 300 AND subclass IN ('wood', 'forest'))
       OR subclass NOT IN ('wood', 'forest')
),

-- z10: all subclasses — cluster small forest/wood
z10 AS (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, 10 AS z_level,
           ST_Transform(ST_MakeValid((ST_Dump(ST_Union(geometry))).geom), 4326) AS geometry
    FROM (
        SELECT subclass, leaf_type, leaf_cycle, intermittent,
               ST_ClusterDBSCAN(geometry, eps := 0, minpoints := 1) OVER (PARTITION BY subclass) AS cid,
               geometry
        FROM z10_simplified
        WHERE vertex_count < 300 AND subclass IN ('wood', 'forest')
    ) c
    GROUP BY subclass, leaf_type, leaf_cycle, intermittent, cid
    UNION ALL
    SELECT subclass, leaf_type, leaf_cycle, intermittent, 10 AS z_level,
           ST_Transform(geometry, 4326) AS geometry
    FROM z10_simplified
    WHERE (vertex_count >= 300 AND subclass IN ('wood', 'forest'))
       OR subclass NOT IN ('wood', 'forest')
),

-- z9: forest+wood+wetlands+coastal — cluster all forest/wood (small and large)
z9 AS (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, 9 AS z_level,
           ST_Transform(ST_MakeValid((ST_Dump(ST_Union(geometry))).geom), 4326) AS geometry
    FROM (
        SELECT subclass, leaf_type, leaf_cycle, intermittent,
               ST_ClusterDBSCAN(geometry, eps := 0, minpoints := 1) OVER (PARTITION BY subclass) AS cid,
               geometry
        FROM z9_simplified
        WHERE subclass IN ('wood', 'forest')
    ) c
    GROUP BY subclass, leaf_type, leaf_cycle, intermittent, cid
    UNION ALL
    SELECT subclass, leaf_type, leaf_cycle, intermittent, 9 AS z_level,
           ST_Transform(geometry, 4326) AS geometry
    FROM z9_simplified
    WHERE subclass IN (
        'bare_rock', 'beach', 'bog', 'dune', 'dune_system', 'fen',
        'mangrove', 'marsh', 'reedbed', 'salt_flat', 'saltmarsh', 'sand', 'scree',
        'shoal', 'string_bog', 'swamp', 'tidalflat', 'unknown_wetland', 'wet_meadow'
    )
),

-- z8: forest+wood+wetlands+coastal — cluster all forest/wood
z8 AS (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, 8 AS z_level,
           ST_Transform(ST_MakeValid((ST_Dump(ST_Union(geometry))).geom), 4326) AS geometry
    FROM (
        SELECT subclass, leaf_type, leaf_cycle, intermittent,
               ST_ClusterDBSCAN(geometry, eps := 0, minpoints := 1) OVER (PARTITION BY subclass) AS cid,
               geometry
        FROM z8_simplified
        WHERE subclass IN ('wood', 'forest')
    ) c
    GROUP BY subclass, leaf_type, leaf_cycle, intermittent, cid
    UNION ALL
    SELECT subclass, leaf_type, leaf_cycle, intermittent, 8 AS z_level,
           ST_Transform(geometry, 4326) AS geometry
    FROM z8_simplified
    WHERE subclass IN (
        'bare_rock', 'beach', 'bog', 'dune', 'dune_system', 'fen', 'glacier',
        'mangrove', 'marsh', 'reedbed', 'salt_flat', 'saltmarsh', 'sand', 'scree',
        'shoal', 'string_bog', 'swamp', 'tidalflat', 'unknown_wetland', 'wet_meadow'
    )
),

-- z7: forest+wood+wetlands+coastal — cluster all subclasses
z7 AS (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, 7 AS z_level,
           ST_Transform(ST_MakeValid((ST_Dump(ST_Union(geometry))).geom), 4326) AS geometry
    FROM (
        SELECT subclass, leaf_type, leaf_cycle, intermittent,
               ST_ClusterDBSCAN(geometry, eps := 0, minpoints := 1) OVER (PARTITION BY subclass) AS cid,
               geometry
        FROM z7_simplified
        WHERE subclass IN (
            'bare_rock', 'beach', 'bog', 'dune', 'dune_system', 'fen', 'forest', 'glacier',
            'mangrove', 'marsh', 'reedbed', 'salt_flat', 'saltmarsh', 'sand', 'scree',
            'shoal', 'string_bog', 'swamp', 'tidalflat', 'unknown_wetland', 'wet_meadow', 'wood'
        )
    ) c
    GROUP BY subclass, leaf_type, leaf_cycle, intermittent, cid
),

-- z6: wetlands+coastal — cluster all
z6 AS (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, 6 AS z_level,
           ST_Transform(ST_MakeValid((ST_Dump(ST_Union(geometry))).geom), 4326) AS geometry
    FROM (
        SELECT subclass, leaf_type, leaf_cycle, intermittent,
               ST_ClusterDBSCAN(geometry, eps := 0, minpoints := 1) OVER (PARTITION BY subclass) AS cid,
               geometry
        FROM z6_simplified
        WHERE subclass IN (
            'bare_rock', 'beach', 'bog', 'dune', 'dune_system', 'fen', 'glacier',
            'mangrove', 'marsh', 'reedbed', 'salt_flat', 'saltmarsh', 'sand', 'scree',
            'shoal', 'string_bog', 'swamp', 'tidalflat', 'unknown_wetland', 'wet_meadow'
        )
    ) c
    GROUP BY subclass, leaf_type, leaf_cycle, intermittent, cid
),

-- z5: coastal only — cluster all
z5 AS (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, 5 AS z_level,
           ST_Transform(ST_MakeValid((ST_Dump(ST_Union(geometry))).geom), 4326) AS geometry
    FROM (
        SELECT subclass, leaf_type, leaf_cycle, intermittent,
               ST_ClusterDBSCAN(geometry, eps := 0, minpoints := 1) OVER (PARTITION BY subclass) AS cid,
               geometry
        FROM z5_simplified
        WHERE subclass IN ('bare_rock', 'beach', 'dune', 'dune_system', 'glacier', 'sand', 'scree', 'shoal')
    ) c
    GROUP BY subclass, leaf_type, leaf_cycle, intermittent, cid
),

-- z4: coastal only — cluster all
z4 AS (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, 4 AS z_level,
           ST_Transform(ST_MakeValid((ST_Dump(ST_Union(geometry))).geom), 4326) AS geometry
    FROM (
        SELECT subclass, leaf_type, leaf_cycle, intermittent,
               ST_ClusterDBSCAN(geometry, eps := 0, minpoints := 1) OVER (PARTITION BY subclass) AS cid,
               geometry
        FROM z4_simplified
        WHERE subclass IN ('bare_rock', 'beach', 'dune', 'dune_system', 'glacier', 'sand', 'scree', 'shoal')
    ) c
    GROUP BY subclass, leaf_type, leaf_cycle, intermittent, cid
)

-- ── Final union ───────────────────────────────────────────────────────────────

SELECT subclass, leaf_type, leaf_cycle, intermittent, z_level,
       ST_Area(geometry::geography)::real                                AS area,
       geometry
FROM (
    SELECT subclass, leaf_type, leaf_cycle, intermittent, z_level,
           (ST_Dump(geometry)).geom                                       AS geometry
    FROM (
        SELECT * FROM z13 WHERE ST_GeometryType(geometry) IN ('ST_Polygon', 'ST_MultiPolygon')
        UNION ALL
        SELECT * FROM z12 WHERE ST_GeometryType(geometry) IN ('ST_Polygon', 'ST_MultiPolygon')
        UNION ALL
        SELECT * FROM z11 WHERE ST_GeometryType(geometry) IN ('ST_Polygon', 'ST_MultiPolygon')
        UNION ALL
        SELECT * FROM z10 WHERE ST_GeometryType(geometry) IN ('ST_Polygon', 'ST_MultiPolygon')
        UNION ALL
        SELECT * FROM z9  WHERE ST_GeometryType(geometry) IN ('ST_Polygon', 'ST_MultiPolygon')
        UNION ALL
        SELECT * FROM z8  WHERE ST_GeometryType(geometry) IN ('ST_Polygon', 'ST_MultiPolygon')
        UNION ALL
        SELECT * FROM z7  WHERE ST_GeometryType(geometry) IN ('ST_Polygon', 'ST_MultiPolygon')
        UNION ALL
        SELECT * FROM z6  WHERE ST_GeometryType(geometry) IN ('ST_Polygon', 'ST_MultiPolygon')
        UNION ALL
        SELECT * FROM z5  WHERE ST_GeometryType(geometry) IN ('ST_Polygon', 'ST_MultiPolygon')
        UNION ALL
        SELECT * FROM z4  WHERE ST_GeometryType(geometry) IN ('ST_Polygon', 'ST_MultiPolygon')
    ) combined
) dumped
WHERE ST_Area(geometry::geography) > 1;

CREATE INDEX idx_landcover_geometry   ON export.landcover_polygon USING gist(geometry);
CREATE INDEX idx_landcover_subclass   ON export.landcover_polygon USING btree(subclass);
CREATE INDEX idx_landcover_z_level    ON export.landcover_polygon USING btree(z_level);
CREATE INDEX idx_landcover_leaf_type  ON export.landcover_polygon USING btree(leaf_type)  WHERE leaf_type  IS NOT NULL;
CREATE INDEX idx_landcover_leaf_cycle ON export.landcover_polygon USING btree(leaf_cycle) WHERE leaf_cycle IS NOT NULL;
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
