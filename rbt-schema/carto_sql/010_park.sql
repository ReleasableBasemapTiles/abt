-- =============================================================================
-- LAYER: Park
-- Schema:        export
-- Sources:       osm.osm_park_polygon
--                osm.osm_landuse_polygon
-- =============================================================================


-- -----------------------------------------------------------------------------
-- export.park_polygon — protected areas and recreational park polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.park_polygon CASCADE;
CREATE MATERIALIZED VIEW export.park_polygon AS
SELECT
    osm_id,
    NULLIF(access, '')                                                  AS access,
    NULLIF(class, '')                                                   AS class,
    COALESCE(
        CASE WHEN leisure IN ('park','nature_reserve','golf_course','dog_park','recreation_ground','garden') THEN leisure END,
        NULLIF(subclass, '')
    )                                                                   AS subclass,
    NULLIF(iucn_level, '')                                              AS iucn_level,
    COALESCE(NULLIF(name_en, ''), NULLIF(name, ''))                     AS name,
    NULLIF(protect_class, '')                                           AS protect_class,
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area,
    MinLabel(ST_Area(ST_Transform(geometry, 3857)))                     AS min_label,
    geometry
FROM osm.osm_park_polygon
WHERE subclass IN (
    'District', 'Regional', 'aboriginal_lands', 'bunker', 'city_park',
    'community', 'county_park', 'dog_park', 'fairway', 'golf_course', 'green',
    'national_park', 'natural_area', 'nature_reserve',
    'neighbourhood', 'park', 'pitch', 'private_park',
    'protected_area', 'recreation_ground', 'regional',
    'special', 'state_beach', 'state_historic_park', 'state_park'
)

UNION ALL

-- leisure=pitch imports to osm_landuse_polygon, not osm_park_polygon
SELECT
    osm_id,
    NULLIF(access, '')                                                  AS access,
    NULLIF(class, '')                                                   AS class,
    NULLIF(subclass, '')                                                AS subclass,
    NULL::text                                                          AS iucn_level,
    COALESCE(NULLIF(name_en, ''), NULLIF(name, ''))                     AS name,
    NULL::text                                                          AS protect_class,
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area,
    MinLabel(ST_Area(ST_Transform(geometry, 3857)))                     AS min_label,
    geometry
FROM osm.osm_landuse_polygon
WHERE subclass = 'pitch';

CREATE INDEX idx_park_geometry      ON export.park_polygon USING gist(geometry);
CREATE INDEX idx_park_osm_id        ON export.park_polygon USING btree(osm_id);
CREATE INDEX idx_park_class         ON export.park_polygon USING btree(class);
CREATE INDEX idx_park_subclass      ON export.park_polygon USING btree(subclass);
CREATE INDEX idx_park_area          ON export.park_polygon USING btree(area);
CREATE INDEX idx_park_iucn_level    ON export.park_polygon USING btree(iucn_level) WHERE iucn_level IS NOT NULL;
CREATE INDEX idx_park_protect_class ON export.park_polygon USING btree(protect_class) WHERE protect_class IS NOT NULL;
CREATE INDEX idx_park_name          ON export.park_polygon USING btree(name) WHERE name IS NOT NULL;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.park_label — one label point per named park (see "Label points" in
-- 001_set_schema.sql). Styles used to label park_polygon itself, which
-- repeats the name on every part and in every tile the park crosses.
--
-- Same-name parks that touch or nearly touch are one label: a reserve is
-- often mapped as several adjacent areas (the sections of Mauna Kea Ice Age
-- Natural Area Reserve), and each drew its own name. ST_ClusterDBSCAN with
-- minpoints 1 groups a park with every same-name park within eps, and eps
-- is in degrees: 0.001° is about 110 m, or less east-west away from the
-- equator. The label goes on the group's largest part, and area is the
-- group's total.
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.park_label CASCADE;
CREATE MATERIALIZED VIEW export.park_label AS
WITH clustered AS (
    SELECT
        osm_id,
        name,
        class,
        subclass,
        protect_class,
        iucn_level,
        area,
        geometry,
        ST_ClusterDBSCAN(geometry, eps := 0.001, minpoints := 1)
            OVER (PARTITION BY name)                                    AS cluster_id
    FROM export.park_polygon
    WHERE name IS NOT NULL
),
parts AS (
    SELECT
        c.*,
        p.part,
        MercatorArea(p.part)                                            AS part_area,
        sum(c.area) OVER (PARTITION BY c.name, c.cluster_id)            AS group_area
    FROM clustered c
    CROSS JOIN LATERAL (SELECT LargestPart(c.geometry) AS part) p
)
SELECT DISTINCT ON (name, cluster_id)
    osm_id,
    name,
    class,
    subclass,
    protect_class,
    iucn_level,
    group_area::real                                                    AS area,
    MinLabel(group_area)                                                AS min_label,
    ST_PointOnSurface(COALESCE(part, geometry))::geometry(Point, 4326)  AS geometry
FROM parts
ORDER BY name, cluster_id, part_area DESC NULLS LAST, osm_id;

CREATE INDEX idx_park_label_geometry ON export.park_label USING gist(geometry);
CREATE INDEX idx_park_label_subclass ON export.park_label USING btree(subclass);
CREATE INDEX idx_park_label_name     ON export.park_label USING btree(name);
COMMIT;
