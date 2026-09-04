-- =============================================================================
-- LAYER: Grain Storage
-- Schema:        export
-- Outputs:       export.grain_polygon
--                export.grain_point
-- Intermediates: infrastructure.grain_srf
--                infrastructure.grain_point
--                infrastructure.grain_srf_pnt
-- Sources:       osm.osm_utility_polygon
--                osm.osm_utility_point
-- =============================================================================


-- -----------------------------------------------------------------------------
-- infrastructure.grain_srf — grain storage polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS infrastructure.grain_srf CASCADE;
CREATE MATERIALIZED VIEW infrastructure.grain_srf AS
SELECT
    osm_id,
    class,
    subclass,
    COALESCE(NULLIF(name_en, ''), NULLIF(name, ''))                     AS name,
    NULLIF(height::text, '')                                            AS height,
    NULLIF(content, '')                                                 AS content,
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area,
    tags,
    geometry
FROM osm.osm_utility_polygon
WHERE subclass = 'silo'
  AND content IN ('grain','crop','silage','wheat','crops','feed','grit');

CREATE INDEX idx_grain_srf_geometry ON infrastructure.grain_srf USING gist(geometry);
CREATE INDEX idx_grain_srf_osm_id   ON infrastructure.grain_srf USING btree(osm_id);
COMMIT;


-- -----------------------------------------------------------------------------
-- infrastructure.grain_point — grain storage points
-- -----------------------------------------------------------------------------
BEGIN;
DROP MATERIALIZED VIEW IF EXISTS infrastructure.grain_point CASCADE;

CREATE MATERIALIZED VIEW infrastructure.grain_point AS
SELECT
    osm_id,
    class,
    subclass,
    COALESCE(NULLIF(name_en, ''), NULLIF(name, ''))                     AS name,
    NULLIF(height::text, '')                                            AS height,
    COALESCE(
        NULLIF(content, ''),
        NULLIF(tags -> 'content', '')
    )                                                                   AS content,
    NULL::real                                                          AS area, -- Added placeholder
    tags,
    geometry
FROM osm.osm_utility_point
WHERE subclass = 'silo'
  AND (
      content IN ('grain','crop')
      OR tags -> 'content' IN ('grain','crop','silage','wheat','crops','feed','grit')
  );

CREATE INDEX idx_grain_point_geometry ON infrastructure.grain_point USING gist(geometry);
CREATE INDEX idx_grain_point_osm_id   ON infrastructure.grain_point USING btree(osm_id);
COMMIT;

-- -----------------------------------------------------------------------------
-- infrastructure.grain_srf_pnt — grain storage polygon centroids
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS infrastructure.grain_srf_pnt CASCADE;
CREATE MATERIALIZED VIEW infrastructure.grain_srf_pnt AS
SELECT
    osm_id,
    class,
    subclass,
    name,
    height,
    content,
    area,
    tags,
    ST_PointOnSurface(geometry)::geometry(Point, 4326)                  AS geometry
FROM infrastructure.grain_srf;

CREATE INDEX idx_grain_srf_pnt_geometry ON infrastructure.grain_srf_pnt USING gist(geometry);
CREATE INDEX idx_grain_srf_pnt_osm_id   ON infrastructure.grain_srf_pnt USING btree(osm_id);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.grain_polygon — grain storage polygon output layer
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.grain_polygon CASCADE;
CREATE MATERIALIZED VIEW export.grain_polygon AS
SELECT * FROM infrastructure.grain_srf;

CREATE INDEX idx_grain_srf_geometry ON export.grain_polygon USING gist(geometry);
CREATE INDEX idx_grain_srf_osm_id   ON export.grain_polygon USING btree(osm_id);
CREATE INDEX idx_grain_srf_subclass ON export.grain_polygon USING btree(subclass);
CREATE INDEX idx_grain_srf_name     ON export.grain_polygon USING btree(name) WHERE name IS NOT NULL;
COMMIT;

-- -----------------------------------------------------------------------------
-- export.grain_point — unified grain storage point output layer
-- -----------------------------------------------------------------------------
BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.grain_point CASCADE;

CREATE MATERIALIZED VIEW export.grain_point AS
SELECT
    osm_id,
    class,
    subclass,
    name,
    height,
    content,
    area,
    tags,
    geometry
FROM infrastructure.grain_point
UNION ALL
SELECT
    osm_id,
    class,
    subclass,
    name,
    height,
    content,
    area,
    tags,
    geometry
FROM infrastructure.grain_srf_pnt;

CREATE INDEX idx_grain_all_points_geometry ON export.grain_point USING gist(geometry);
CREATE INDEX idx_grain_all_points_osm_id   ON export.grain_point USING btree(osm_id);
CREATE INDEX idx_grain_all_points_subclass ON export.grain_point USING btree(subclass);
CREATE INDEX idx_grain_all_points_name     ON export.grain_point USING btree(name) WHERE name IS NOT NULL;
COMMIT;
