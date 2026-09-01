-- =============================================================================
-- LAYER: Utility Point
-- Schema:        export
-- Sources:       osm.osm_utility_point
--                osm.osm_building_polygon
--                aux_data.ne_10m_land
-- =============================================================================

-- -----------------------------------------------------------------------------
-- export.utility_point — infrastructure point features
-- -----------------------------------------------------------------------------
BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.utility_point CASCADE;

CREATE MATERIALIZED VIEW export.utility_point AS
WITH wind_onshore AS (
    -- Resolve on/offshore once for all wind generators rather than row-by-row EXISTS.
    -- ST_Intersects against ne_10m_land for 18k+ points is the main cost driver.
    SELECT DISTINCT u.osm_id
    FROM osm.osm_utility_point u
    JOIN aux_data.ne_10m_land land
      ON u.geometry && land.geometry
     AND ST_Intersects(u.geometry, land.geometry)
    WHERE u.generator_source = 'wind'
)
SELECT
    u.osm_id,
    NULLIF(u.class, '')                                                 AS class,
    NULLIF(u.subclass, '')                                              AS subclass,
    COALESCE(NULLIF(u.name_en, ''), NULLIF(u.name, ''))                 AS name,
    NULLIF(u.substation, '')                                            AS substation,
    NULLIF(u.pumping_station, '')                                       AS pumping_station,
    NULLIF(u.operator, '')                                              AS operator,
    NULLIF(u.plant_source, '')                                          AS plant_source,
    NULLIF(u.plant_method, '')                                          AS plant_method,
    NULLIF(u.plant_storage, '')                                         AS plant_storage,
    NULLIF(u.plant_output, '')                                          AS plant_output,
    NULLIF(u.generator_source, '')                                      AS generator_source,
    NULLIF(u.generator_method, '')                                      AS generator_method,
    NULLIF(u.generator_type, '')                                        AS generator_type,
    NULLIF(u.generator_output, '')                                      AS generator_output,
    NULLIF(u.generator_plant, '')                                       AS generator_plant,
    NULLIF(u.seamark_pylon_category, '')                                AS seamark_pylon_category,
    NULLIF(u.seamark_platform_category, '')                             AS seamark_platform_category,
    NULLIF(u.seamark_production_area_category, '')                      AS seamark_production_area_category,
    NULLIF(u.seamark_name, '')                                          AS seamark_name,
    NULLIF(u.seamark_platform_height, '')                               AS seamark_platform_height,
    NULLIF(u.tower_type, '')                                            AS tower_type,
    NULLIF(u.tower_construction, '')                                    AS tower_construction,
    NULLIF(u.mast_type, '')                                             AS mast_type,
    NULLIF(u.rotor_diameter, '')                                        AS rotor_diameter,
    NULLIF(u.service, '')                                               AS service,
    CASE
        WHEN btrim(u.height::text) ~* '^[0-9]+([.,][0-9]+)?\s*m?$'
            THEN replace(regexp_replace(btrim(u.height::text), '[^0-9.,]', '', 'g'), ',', '.')
        ELSE NULL
    END                                                                 AS height,
    NULLIF(u.content, '')                                               AS content,
    NULLIF(u.substance, '')                                             AS substance,
    NULLIF(u.capacity, '')                                              AS capacity,
    NULLIF(u.location, '')                                              AS location,
    NULLIF(u.access, '')                                                AS access,
    
    -- Calculated 'shore' attribute — only relevant for wind generators
    CASE
        WHEN u.generator_source = 'wind' AND wo.osm_id IS NOT NULL THEN 'on'
        WHEN u.generator_source = 'wind'                           THEN 'off'
        ELSE NULL
    END                                                                 AS shore,
    
    u.geometry
FROM osm.osm_utility_point u
LEFT JOIN wind_onshore wo ON wo.osm_id = u.osm_id
WHERE u.subclass IN (
    'oil_well', 'petroleum_well', 'antenna', 'chimney',
    'communications_tower', 'crane', 'flare', 'gasometer',
    'lighthouse', 'mast', 'obelisk', 'offshore_platform',
    'pumping_station', 'silo', 'storage_tank', 'stupa',
    'tower', 'utility_pole', 'water_tower', 'windmill',
    'windpump', 'generator', 'pole', 'portal', 'substation',
    'light_major', 'platform', 'pylon', 'gate'
)

UNION ALL

-- man_made towers/tanks/silos mapped as building polygons (building=yes + man_made=X)
SELECT
    b.osm_id,
    'man_made'::text                                                    AS class,
    b.man_made                                                          AS subclass,
    COALESCE(NULLIF(b.name_en, ''), NULLIF(b.name, ''))                 AS name,
    NULLIF(b.tags -> 'substation', '')                                  AS substation,
    NULLIF(b.tags -> 'pumping_station', '')                             AS pumping_station,
    NULLIF(b.tags -> 'operator', '')                                    AS operator,
    NULLIF(b.tags -> 'plant:source', '')                                AS plant_source,
    NULLIF(b.tags -> 'plant:method', '')                                AS plant_method,
    NULLIF(b.tags -> 'plant:storage', '')                               AS plant_storage,
    NULLIF(b.tags -> 'plant:output', '')                                AS plant_output,
    NULLIF(b.tags -> 'generator:source', '')                            AS generator_source,
    NULLIF(b.tags -> 'generator:method', '')                            AS generator_method,
    NULLIF(b.tags -> 'generator:type', '')                              AS generator_type,
    NULLIF(b.tags -> 'generator:output', '')                            AS generator_output,
    NULLIF(b.tags -> 'generator:plant', '')                             AS generator_plant,
    NULLIF(b.tags -> 'seamark:pylon:category', '')                      AS seamark_pylon_category,
    NULLIF(b.tags -> 'seamark:platform:category', '')                   AS seamark_platform_category,
    NULLIF(b.tags -> 'seamark:production_area:category', '')            AS seamark_production_area_category,
    NULLIF(b.tags -> 'seamark:name', '')                                AS seamark_name,
    NULLIF(b.tags -> 'seamark:platform:height', '')                     AS seamark_platform_height,
    NULLIF(b.tower_type, '')                                            AS tower_type,
    NULLIF(b.tower_construction, '')                                    AS tower_construction,
    NULLIF(b.tags -> 'mast:type', '')                                   AS mast_type,
    NULLIF(b.tags -> 'rotor:diameter', '')                              AS rotor_diameter,
    NULLIF(b.tags -> 'service', '')                                     AS service,
    CASE
        WHEN btrim(b.height) ~* '^[0-9]+([.,][0-9]+)?\s*m?$'
            THEN replace(regexp_replace(btrim(b.height), '[^0-9.,]', '', 'g'), ',', '.')
        ELSE NULL
    END                                                                 AS height,
    NULLIF(b.tags -> 'content', '')                                     AS content,
    NULLIF(b.tags -> 'substance', '')                                   AS substance,
    NULLIF(b.tags -> 'capacity', '')                                    AS capacity,
    NULLIF(b.tags -> 'location', '')                                    AS location,
    NULLIF(b.tags -> 'access', '')                                      AS access,
    NULL::text                                                          AS shore,
    ST_PointOnSurface(b.geometry)::geometry(Point, 4326)                AS geometry
FROM osm.osm_building_polygon b
WHERE b.man_made IN (
    'storage_tank', 'oil_well', 'petroleum_well', 'offshore_platform',
    'lighthouse', 'communications_tower', 'tower', 'mast', 'antenna',
    'utility_pole', 'pole', 'water_tower', 'substation', 'transmission',
    'silo', 'telescope', 'lock_gate'
);

CREATE INDEX idx_utility_point_geometry ON export.utility_point USING gist(geometry);
CREATE INDEX idx_utility_point_osm_id   ON export.utility_point USING btree(osm_id);
CREATE INDEX idx_utility_point_class    ON export.utility_point USING btree(class);
CREATE INDEX idx_utility_point_subclass ON export.utility_point USING btree(subclass);
CREATE INDEX idx_utility_point_name     ON export.utility_point USING btree(name) WHERE name IS NOT NULL;

COMMIT;
