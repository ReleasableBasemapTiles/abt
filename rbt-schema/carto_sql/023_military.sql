-- =============================================================================
-- LAYER: Military and Security Infrastructure
-- Schema:        export
-- Sources:       osm.osm_utility_point
--                osm.osm_building_polygon
--                aux_data.mirtalocations_a
--                osm.osm_builtup_area
-- =============================================================================


-- -----------------------------------------------------------------------------
-- export.radar_label — radar tower point features
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.radar_label CASCADE;
CREATE MATERIALIZED VIEW export.radar_label AS
SELECT
    osm_id,
    class,
    subclass,
    NULLIF(name, '')                                                    AS name,
    NULLIF(name_en, '')                                                 AS name_en,
    NULLIF(operator, '')                                                AS operator,
    NULLIF(seamark_name, '')                                            AS seamark_name,
    NULLIF(tower_type, '')                                              AS tower_type,
    NULLIF(tower_construction, '')                                      AS tower_construction,
    NULLIF(mast_type, '')                                               AS mast_type,
    NULLIF(service, '')                                                 AS service,
    NULLIF(height::text, '')                                            AS height,
    NULLIF(access, '')                                                  AS access,
    NULLIF(tags -> 'military', '')                                      AS military,
    NULLIF(tags -> 'ele', '')                                           AS ele,
    NULLIF(tags -> 'airmark', '')                                       AS airmark,
    NULLIF(tags -> 'radar', '')                                         AS radar,
    NULLIF(tags -> 'description', '')                                   AS description,
    geometry
FROM osm.osm_utility_point
WHERE tower_type = 'radar'

UNION ALL

-- radar towers mapped as building polygons (building=yes + man_made=tower + tower:type=radar)
SELECT
    osm_id,
    'man_made'::text                                                    AS class,
    'tower'::text                                                       AS subclass,
    NULLIF(name, '')                                                    AS name,
    NULLIF(name_en, '')                                                 AS name_en,
    NULLIF(tags -> 'operator', '')                                      AS operator,
    NULLIF(tags -> 'seamark:name', '')                                  AS seamark_name,
    NULLIF(tower_type, '')                                              AS tower_type,
    NULLIF(tower_construction, '')                                      AS tower_construction,
    NULLIF(tags -> 'mast:type', '')                                     AS mast_type,
    NULLIF(tags -> 'service', '')                                       AS service,
    NULLIF(height, '')                                                  AS height,
    NULLIF(tags -> 'access', '')                                        AS access,
    NULLIF(tags -> 'military', '')                                      AS military,
    NULLIF(tags -> 'ele', '')                                           AS ele,
    NULLIF(tags -> 'airmark', '')                                       AS airmark,
    NULLIF(tags -> 'radar', '')                                         AS radar,
    NULLIF(tags -> 'description', '')                                   AS description,
    ST_PointOnSurface(geometry)::geometry(Point, 4326)                  AS geometry
FROM osm.osm_building_polygon
WHERE tower_type = 'radar';

CREATE INDEX idx_radar_point_geometry ON export.radar_label USING gist(geometry);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.us_military_installations_polygon — US military installation polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.us_military_installations_polygon CASCADE;
CREATE MATERIALIZED VIEW export.us_military_installations_polygon AS
SELECT
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area,
    NULLIF(sitereportingcomponent, '')                                  AS component,
    NULLIF(countryname, '')                                             AS country,
    NULLIF(isjointbase, '')                                             AS jointbase,
    NULLIF(siteoperationalstatus, '')                                   AS operstatus,
    NULLIF(sitename, '')                                                AS sitename,
    NULLIF(statenamecode, '')                                           AS state,
    geometry
FROM aux_data.mirtalocations_a;

CREATE INDEX idx_us_mil_inst_geometry ON export.us_military_installations_polygon USING gist(geometry);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.us_military_installations_label — label points for US military installations
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.us_military_installations_label CASCADE;
CREATE MATERIALIZED VIEW export.us_military_installations_label AS
SELECT
    area,
    component,
    country,
    jointbase,
    operstatus,
    sitename,
    state,
    ST_PointOnSurface(geometry)                                         AS geometry
FROM export.us_military_installations_polygon

UNION ALL

-- Guantanamo Bay is not in MIRTA (CONUS only). Area approximated from real-world
-- footprint (~45 sq mi) so the label appears at zoom 10 per the layer visibility style.
SELECT
    116500000::real                                                      AS area,
    NULL::text                                                           AS component,
    'Cuba'::text                                                         AS country,
    NULL::text                                                           AS jointbase,
    NULL::text                                                           AS operstatus,
    'US Naval Base Guantanamo Bay'::text                                 AS sitename,
    NULL::text                                                           AS state,
    ST_SetSRID(ST_MakePoint(-75.16, 19.9175), 4326)                     AS geometry;

CREATE INDEX idx_us_mil_inst_labels_geometry ON export.us_military_installations_label USING gist(geometry);
COMMIT;