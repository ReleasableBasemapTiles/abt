-- =============================================================================
-- LAYER: Power Station
-- Schema:        export
-- Intermediates: infrastructure.power_station
-- Sources:       osm.osm_utility_polygon
-- =============================================================================


-- -----------------------------------------------------------------------------
-- infrastructure.power_station — power plant and generator polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS infrastructure.power_station CASCADE;
CREATE MATERIALIZED VIEW infrastructure.power_station AS
SELECT
    osm_id,
    CASE WHEN subclass = 'plant_part' THEN 'plant' ELSE subclass END      AS subclass,
    COALESCE(NULLIF(name_en, ''), NULLIF(name, ''))                     AS name,
    NULLIF(operator, '')                                                AS operator,
    NULLIF(plant_source, '')                                            AS plant_source,
    NULLIF(plant_method, '')                                            AS plant_method,
    NULLIF(plant_storage, '')                                           AS plant_storage,
    NULLIF(plant_output, '')                                            AS plant_output,
    NULLIF(generator_source, '')                                        AS generator_source,
    NULLIF(generator_method, '')                                        AS generator_method,
    NULLIF(generator_type, '')                                          AS generator_type,
    NULLIF(generator_output, '')                                        AS generator_output,
    NULLIF(generator_plant, '')                                         AS generator_plant,
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area,
    geometry
FROM osm.osm_utility_polygon
WHERE class = 'power';

CREATE INDEX idx_power_station_geometry ON infrastructure.power_station USING gist(geometry);
CREATE INDEX idx_power_station_osm_id   ON infrastructure.power_station USING btree(osm_id);
CREATE INDEX idx_power_station_subclass ON infrastructure.power_station USING btree(subclass);
CREATE INDEX idx_power_station_name     ON infrastructure.power_station USING btree(name) WHERE name IS NOT NULL;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.power_station — power station polygon output layer
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.power_station_polygon CASCADE;
CREATE MATERIALIZED VIEW export.power_station_polygon AS
SELECT * FROM infrastructure.power_station;

CREATE INDEX idx_power_station_geometry ON export.power_station_polygon USING gist(geometry);
CREATE INDEX idx_power_station_osm_id   ON export.power_station_polygon USING btree(osm_id);
CREATE INDEX idx_power_station_subclass ON export.power_station_polygon USING btree(subclass);
CREATE INDEX idx_power_station_name     ON export.power_station_polygon USING btree(name) WHERE name IS NOT NULL;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.power_station_label — label points for power stations
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.power_station_label CASCADE;
CREATE MATERIALIZED VIEW export.power_station_label AS
SELECT
    osm_id,
    subclass,
    name,
    operator,
    plant_source,
    plant_method,
    plant_storage,
    plant_output,
    generator_source,
    generator_method,
    generator_type,
    generator_output,
    generator_plant,
    area,
    ST_PointOnSurface(geometry)::geometry(Point, 4326)                  AS geometry
FROM infrastructure.power_station;

CREATE INDEX idx_power_station_label_geometry ON export.power_station_label USING gist(geometry);
CREATE INDEX idx_power_station_label_osm_id   ON export.power_station_label USING btree(osm_id);
CREATE INDEX idx_power_station_label_subclass ON export.power_station_label USING btree(subclass);
CREATE INDEX idx_power_station_label_name     ON export.power_station_label USING btree(name) WHERE name IS NOT NULL;
COMMIT;


