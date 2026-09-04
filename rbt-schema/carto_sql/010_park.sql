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
