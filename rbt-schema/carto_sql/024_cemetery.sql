-- =============================================================================
-- LAYER: Cemetery
-- Schema:        export
-- Intermediates: landuse.tmp_cemetery_ranked
-- Sources:       osm.osm_landuse_polygon
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Cleanup
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS landuse.tmp_cemetery_ranked CASCADE;

-- -----------------------------------------------------------------------------
-- Step 1: Create temp table with cemetery data
-- -----------------------------------------------------------------------------
CREATE TABLE landuse.tmp_cemetery_ranked AS
WITH dumped AS (
    SELECT
        osm_id,
        COALESCE(NULLIF(name_en, ''), NULLIF(name, ''))                 AS name,
        NULLIF(class, '')                                               AS class,
        NULLIF(subclass, '')                                            AS subclass,
        NULLIF(tags -> 'religion', '')                                  AS religion,
        NULLIF(tags -> 'denomination', '')                              AS denomination,
        NULLIF(tags -> 'cemetery', '')                                  AS cemetery,
        ST_Area(ST_Transform(geometry, 3857))::real                     AS area,
        (ST_Dump(geometry)).geom::geometry(Polygon, 4326)               AS geometry
    FROM osm.osm_landuse_polygon
    WHERE geometry IS NOT NULL
      AND (subclass ILIKE '%cemetery%'
           OR subclass ILIKE '%graveyard%'
           OR subclass = 'grave_yard'
           OR subclass IN ('grave', 'gravesite', 'burial_ground'))

)
SELECT
    ROW_NUMBER() OVER (ORDER BY geometry)                               AS fid,
    *,
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area_part,
    RANK() OVER (PARTITION BY name ORDER BY ST_Area(ST_Transform(geometry, 3857)) DESC) AS rank
FROM dumped;

CREATE INDEX idx_tmp_cemetery_gist ON landuse.tmp_cemetery_ranked USING gist(geometry);

-- -----------------------------------------------------------------------------
-- Step 2: Create cemetery_polygon view (non-contained polygons only)
-- -----------------------------------------------------------------------------
CREATE MATERIALIZED VIEW export.cemetery_polygon AS
SELECT
    a.fid,
    a.osm_id,
    a.name,
    a.class,
    a.subclass,
    a.religion,
    a.denomination,
    a.cemetery,
    a.area,
    a.area_part,
    a.rank,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM landuse.tmp_cemetery_ranked b
            WHERE a.fid != b.fid
              AND a.geometry && b.geometry
              AND ST_ContainsProperly(b.geometry, a.geometry)
        ) THEN 1
        ELSE 0
    END AS contained,
    a.geometry
FROM landuse.tmp_cemetery_ranked a
WHERE NOT EXISTS (
    SELECT 1 FROM landuse.tmp_cemetery_ranked b
    WHERE a.fid != b.fid
      AND a.geometry && b.geometry
      AND ST_ContainsProperly(b.geometry, a.geometry)
);

CREATE INDEX idx_cemetery_geometry ON export.cemetery_polygon USING gist(geometry);

-- -----------------------------------------------------------------------------
-- Step 3: Create cemetery_label view (label points)
-- -----------------------------------------------------------------------------
CREATE MATERIALIZED VIEW export.cemetery_label AS
SELECT
    fid,
    osm_id,
    name,
    class,
    subclass,
    religion,
    denomination,
    cemetery,
    area,
    area_part,
    rank,
    contained,
    ST_PointOnSurface(geometry)::geometry(Point, 4326)                  AS geometry
FROM export.cemetery_polygon;

CREATE INDEX idx_cemetery_label_geometry ON export.cemetery_label USING gist(geometry);