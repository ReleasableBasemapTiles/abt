-- =============================================================================
-- LAYER: Pumping Station
-- Schema:        export
-- Intermediates: infrastructure.pumping_station
-- Sources:       osm.osm_utility_polygon
-- =============================================================================


-- -----------------------------------------------------------------------------
-- infrastructure.pumping_station — pumping station and substation polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS infrastructure.pumping_station CASCADE;
CREATE MATERIALIZED VIEW infrastructure.pumping_station AS
SELECT
    osm_id,
    subclass,
    COALESCE(NULLIF(name_en, ''), NULLIF(name, ''))                     AS name,
    NULLIF(operator, '')                                                AS operator,
    NULLIF(substation, '')                                              AS substation,
    NULLIF(substance, '')                                               AS substance,
    NULLIF(pumping_station, '')                                         AS pumping_station,
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area,
    geometry
FROM osm.osm_utility_polygon
WHERE class != 'power';

CREATE INDEX idx_pumping_station_geometry ON infrastructure.pumping_station USING gist(geometry);
CREATE INDEX idx_pumping_station_osm_id   ON infrastructure.pumping_station USING btree(osm_id);
CREATE INDEX idx_pumping_station_subclass ON infrastructure.pumping_station USING btree(subclass);
CREATE INDEX idx_pumping_station_name     ON infrastructure.pumping_station USING btree(name) WHERE name IS NOT NULL;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.pumping_station — pumping station polygon output layer
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.pumping_station_polygon CASCADE;
CREATE MATERIALIZED VIEW export.pumping_station_polygon AS
SELECT * FROM infrastructure.pumping_station;

CREATE INDEX idx_pumping_station_geometry ON export.pumping_station_polygon USING gist(geometry);
CREATE INDEX idx_pumping_station_osm_id   ON export.pumping_station_polygon USING btree(osm_id);
CREATE INDEX idx_pumping_station_subclass ON export.pumping_station_polygon USING btree(subclass);
CREATE INDEX idx_pumping_station_name     ON export.pumping_station_polygon USING btree(name) WHERE name IS NOT NULL;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.pumping_station_label — label points for pumping stations
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.pumping_station_label CASCADE;
CREATE MATERIALIZED VIEW export.pumping_station_label AS
SELECT
    osm_id,
    subclass,
    name,
    operator,
    substation,
    substance,
    pumping_station,
    area,
    ST_PointOnSurface(geometry)::geometry(Point, 4326)                  AS geometry
FROM infrastructure.pumping_station;

CREATE INDEX idx_pumping_station_label_geometry ON export.pumping_station_label USING gist(geometry);
CREATE INDEX idx_pumping_station_label_osm_id   ON export.pumping_station_label USING btree(osm_id);
CREATE INDEX idx_pumping_station_label_subclass ON export.pumping_station_label USING btree(subclass);
CREATE INDEX idx_pumping_station_label_name     ON export.pumping_station_label USING btree(name) WHERE name IS NOT NULL;
COMMIT;
