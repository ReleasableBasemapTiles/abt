-- =============================================================================
-- LAYER: Railway
-- Schema:        export
-- Intermediates: transportation.railway_normalized
-- Sources:       osm.osm_railway_linestring
--                osm.osm_transportation_polygon
--                osm.osm_transportation_point
-- =============================================================================


-- -----------------------------------------------------------------------------
-- transportation.railway_normalized — lifecycle, gauge, electrification,
--                                     track count, service and usage classifiers
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS transportation.railway_normalized CASCADE;
CREATE MATERIALIZED VIEW transportation.railway_normalized AS
SELECT
    osm_id,
    CASE
        WHEN subclass IN (
            'construction', 'proposed', 'planned',
            'destroyed', 'demolished', 'razed', 'removed', 'disused', 'abandoned', 'ruins'
        ) THEN subclass
        ELSE 'intact'
    END                                                             AS lifecycle_type,
    CASE
        WHEN subclass = 'construction' THEN NULLIF(TRIM(construction), '')
        WHEN subclass = 'proposed'     THEN NULLIF(TRIM(proposed), '')
        WHEN subclass = 'planned'      THEN NULLIF(TRIM(planned), '')
        WHEN subclass = 'destroyed'    THEN NULLIF(TRIM(destroyed), '')
        WHEN subclass = 'demolished'   THEN NULLIF(TRIM(demolished), '')
        WHEN subclass = 'razed'        THEN NULLIF(TRIM(razed), '')
        WHEN subclass = 'removed'      THEN NULLIF(TRIM(removed), '')
        WHEN subclass = 'disused'      THEN NULLIF(TRIM(disused), '')
        WHEN subclass = 'abandoned'    THEN NULLIF(TRIM(abandoned), '')
        WHEN subclass = 'ruins'        THEN NULLIF(TRIM(ruins), '')
        ELSE NULL
    END                                                             AS lifecycle_desc,
    CASE
        WHEN subclass IN ('narrow_gauge', 'miniature')                                  THEN 'narrow'
        WHEN gauge IS NULL OR gauge IN ('railway', 'rail', 'unknown', 'no', 'standard')
             OR gauge ILIKE '14%'                                                       THEN 'standard'
        WHEN gauge IN ('wide', 'broad') OR gauge ~ '^(15|16|17|18|19|2\d{3})'          THEN 'broad'
        ELSE 'narrow'
    END                                                             AS gauge,
    CASE
        WHEN electrified IN ('FIXME', 'no', 'NO', 'unknown') OR electrified IS NULL
             AND subclass NOT IN ('tram', 'monorail', 'subway', 'light_rail', 'funicular') THEN 0
        ELSE 1
    END                                                             AS electrified,
    CASE
        WHEN tracks IN ('1', 'single', 'tram', 'monorail') OR NULLIF(TRIM(tracks), '') IS NULL THEN 'single'
        ELSE 'multiple'
    END                                                             AS tracks,
    CASE
        WHEN LOWER(service) % 'siding'    OR LOWER(service) % 'siting'             THEN 'siding'
        WHEN LOWER(service) % 'spur'                                                THEN 'spur'
        WHEN LOWER(service) % 'crossover'                                           THEN 'crossover'
        WHEN LOWER(service) % 'yard'                                                THEN 'yard'
        ELSE NULL
    END                                                             AS service,
    CASE
        WHEN LOWER(usage) % 'siding'                                                THEN 'siding'
        WHEN LOWER(usage) % 'spur'                                                  THEN 'spur'
        WHEN LOWER(usage) % 'crossover'                                             THEN 'crossover'
        WHEN LOWER(usage) % 'yard'                                                  THEN 'yard'
        WHEN LOWER(usage) % 'branch'                                                THEN 'branch'
        WHEN LOWER(usage) % 'industrial'                                            THEN 'industrial'
        WHEN LOWER(usage) % 'main' AND LOWER(usage) != 'maintenance'               THEN 'main'
        WHEN LOWER(usage) % 'tourism' OR LOWER(usage) % 'tourist'                  THEN 'tourism'
        ELSE NULLIF(TRIM(usage), '')
    END                                                             AS usage
FROM osm.osm_railway_linestring
WHERE NOT is_area;

CREATE INDEX idx_railway_normalized_osm_id ON transportation.railway_normalized USING btree(osm_id);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.yard_label — railway yard label points (polygon + point sources)
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.yard_label CASCADE;
CREATE MATERIALIZED VIEW export.yard_label AS
SELECT
    osm_id,
    'polygon'                                                       AS source,
    subclass,
    NULLIF(TRIM(operator), '')                                      AS operator,
    COALESCE(NULLIF(TRIM(name_en), ''), NULLIF(TRIM(name), ''))     AS name,
    NULLIF(TRIM(ref), '')                                           AS ref,
    NULLIF(TRIM(service), '')                                       AS service,
    NULLIF(TRIM(usage), '')                                         AS usage,
    CASE
        WHEN yard_size ILIKE '%very%large%' THEN 'very_large'
        WHEN yard_size ILIKE '%very%small%' THEN 'very_small'
        WHEN yard_size ILIKE '%large%'      THEN 'large'
        WHEN yard_size ILIKE '%medium%'     THEN 'medium'
        WHEN yard_size ILIKE '%small%'      THEN 'small'
        ELSE NULLIF(TRIM(yard_size), '')
    END                                                             AS yard_size,
    NULLIF(TRIM(yard_purpose), '')                                  AS yard_purpose,
    ST_PointOnSurface(geometry)::geometry(Point, 4326)              AS geometry
FROM osm.osm_transportation_polygon
WHERE subclass = 'yard' OR LOWER(service) = 'yard'

UNION ALL

SELECT
    osm_id,
    'point'                                                         AS source,
    subclass,
    NULLIF(TRIM(operator), '')                                      AS operator,
    COALESCE(NULLIF(TRIM(name_en), ''), NULLIF(TRIM(name), ''))     AS name,
    NULLIF(TRIM(ref), '')                                           AS ref,
    NULLIF(TRIM(service), '')                                       AS service,
    NULLIF(TRIM(usage), '')                                         AS usage,
    CASE
        WHEN yard_size ILIKE '%very%large%' THEN 'very_large'
        WHEN yard_size ILIKE '%very%small%' THEN 'very_small'
        WHEN yard_size ILIKE '%large%'      THEN 'large'
        WHEN yard_size ILIKE '%medium%'     THEN 'medium'
        WHEN yard_size ILIKE '%small%'      THEN 'small'
        ELSE NULLIF(TRIM(yard_size), '')
    END                                                             AS yard_size,
    NULLIF(TRIM(yard_purpose), '')                                  AS yard_purpose,
    geometry
FROM osm.osm_transportation_point
WHERE subclass = 'yard' OR LOWER(service) = 'yard';

CREATE INDEX idx_yard_label_geometry ON export.yard_label USING gist(geometry);
CREATE INDEX idx_yard_label_osm_id   ON export.yard_label USING btree(osm_id);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.rail_line — railway line output layer
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.rail_line CASCADE;
CREATE MATERIALIZED VIEW export.rail_line AS
SELECT
    r.osm_id,
    r.geometry,
    CASE
        WHEN r.is_bridge THEN 'bridge'
        WHEN r.is_tunnel THEN 'tunnel'
        WHEN r.is_ford   THEN 'ford'
    END                                                             AS brunnel,
    CASE lower(r.subclass)
        WHEN 'construction' THEN COALESCE(NULLIF(TRIM(LOWER(r.construction)),           ''),
                                          NULLIF(TRIM(LOWER(r.tags -> 'construction:railway')), ''),
                                          'unknown')
        WHEN 'proposed'     THEN COALESCE(NULLIF(TRIM(LOWER(r.proposed)),               ''),
                                          NULLIF(TRIM(LOWER(r.tags -> 'proposed:railway')),     ''),
                                          'unknown')
        WHEN 'planned'      THEN COALESCE(NULLIF(TRIM(LOWER(r.planned)),                ''),
                                          NULLIF(TRIM(LOWER(r.tags -> 'planned:railway')),      ''),
                                          'unknown')
        WHEN 'disused'      THEN COALESCE(NULLIF(TRIM(LOWER(r.disused)),                ''),
                                          NULLIF(TRIM(LOWER(r.tags -> 'disused:railway')),      ''),
                                          'unknown')
        WHEN 'abandoned'    THEN COALESCE(NULLIF(TRIM(LOWER(r.abandoned)),              ''),
                                          NULLIF(TRIM(LOWER(r.tags -> 'abandoned:railway')),    ''),
                                          'unknown')
        WHEN 'demolished'   THEN COALESCE(NULLIF(TRIM(LOWER(r.demolished)),             ''),
                                          NULLIF(TRIM(LOWER(r.tags -> 'demolished:railway')),   ''),
                                          'unknown')
        WHEN 'razed'        THEN COALESCE(NULLIF(TRIM(LOWER(r.razed)),                  ''),
                                          NULLIF(TRIM(LOWER(r.tags -> 'razed:railway')),        ''),
                                          'unknown')
        WHEN 'removed'      THEN COALESCE(NULLIF(TRIM(LOWER(r.removed)),                ''),
                                          NULLIF(TRIM(LOWER(r.tags -> 'removed:railway')),      ''),
                                          'unknown')
        ELSE r.subclass
    END                                                                 AS subclass,
    COALESCE(NULLIF(TRIM(r.name_en), ''), NULLIF(TRIM(r.name), '')) AS name,
    NULLIF(TRIM(r.ref), '')                                         AS ref,
    NULLIF(TRIM(r.network), '')                                     AS network,
    NULLIF(TRIM(r.voltage), '')                                     AS voltage,
    NULLIF(TRIM(r.frequency), '')                                   AS frequency,
    NULLIF(TRIM(r.bridge_name), '')                                 AS bridge_name,
    NULLIF(TRIM(r.tunnel_name), '')                                 AS tunnel_name,
    n.service,
    n.usage,
    n.gauge,
    n.electrified,
    n.tracks,
    n.lifecycle_type,
    r.layer,
    r.level,
    r.is_oneway,
    r.is_ramp,
    CASE
        WHEN n.service IS NULL AND n.lifecycle_type = 'intact' THEN
            'railway_intact_' ||
            CASE WHEN n.gauge = 'narrow' THEN 'narrow' ELSE 'broadstandard' END || '_' ||
            CASE WHEN n.electrified = 1  THEN 'electrified' ELSE 'nonelectrified' END || '_' ||
            CASE WHEN n.tracks = 'single' THEN 'singletrack' ELSE 'multipletracks' END
        WHEN n.service IS NOT NULL AND n.lifecycle_type = 'intact' THEN
            'sidetrack_intact_' ||
            CASE WHEN n.gauge = 'narrow' THEN 'narrow' ELSE 'broadstandard' END || '_' ||
            CASE WHEN n.electrified = 1  THEN 'electrified' ELSE 'nonelectrified' END
        WHEN n.service IS NULL AND n.lifecycle_type != 'intact' THEN
            'railway_not-intact_' ||
            CASE WHEN n.gauge = 'narrow' THEN 'narrow' ELSE 'broadstandard' END || '_' ||
            CASE WHEN n.electrified = 1  THEN 'electrified' ELSE 'nonelectrified' END || '_' ||
            CASE WHEN n.tracks = 'single' THEN 'singletrack' ELSE 'multipletracks' END
        WHEN n.service IS NOT NULL AND n.lifecycle_type != 'intact' THEN
            'sidetrack_not-intact_' ||
            CASE WHEN n.gauge = 'narrow' THEN 'narrow' ELSE 'broadstandard' END || '_' ||
            CASE WHEN n.electrified = 1  THEN 'electrified' ELSE 'nonelectrified' END
    END                                                             AS dps_type
FROM osm.osm_railway_linestring r
LEFT JOIN transportation.railway_normalized n ON r.osm_id = n.osm_id
WHERE NOT r.is_area
  AND COALESCE(n.lifecycle_type, 'intact') != 'abandoned';

CREATE INDEX idx_railway_geometry ON export.rail_line USING gist(geometry);
CREATE UNIQUE INDEX idx_railway_osm_id ON export.rail_line USING btree(osm_id);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.transportation_station — transportation station polygon output layer
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.rail_station CASCADE;
DROP MATERIALIZED VIEW IF EXISTS export.transportation_station CASCADE;
DROP MATERIALIZED VIEW IF EXISTS export.transportation_station_polygon CASCADE;
CREATE MATERIALIZED VIEW export.transportation_station_polygon AS
SELECT
    osm_id,
    class,
    subclass,
    NULLIF(name, '')                                                AS name,
    NULLIF(tags -> 'platforms', '')                                 AS platforms,
    NULLIF(operator, '')                                            AS operator,
    NULLIF(station, '')                                             AS station,
    NULLIF(service, '')                                             AS service,
    ST_Area(ST_Transform(geometry, 3857))::real                     AS area,
    geometry
FROM osm.osm_transportation_polygon
WHERE subclass IN ('station', 'bus_station', 'ferry_terminal', 'rest_area', 'services', 'platform');

CREATE INDEX idx_transportation_station_geometry ON export.transportation_station_polygon USING gist(geometry);
CREATE INDEX idx_transportation_station_osm_id   ON export.transportation_station_polygon USING btree(osm_id);
CREATE INDEX idx_transportation_station_subclass ON export.transportation_station_polygon USING btree(subclass);
CREATE INDEX idx_transportation_station_name     ON export.transportation_station_polygon USING btree(name) WHERE name IS NOT NULL;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.transportation_station_label — transportation station label points
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.rail_station_label CASCADE;
DROP MATERIALIZED VIEW IF EXISTS export.transportation_station_label CASCADE;
CREATE MATERIALIZED VIEW export.transportation_station_label AS
SELECT
    osm_id,
    class,
    subclass,
    NULLIF(name, '')                                                AS name,
    NULLIF(tags -> 'platforms', '')                                 AS platforms,
    NULLIF(operator, '')                                            AS operator,
    NULLIF(station, '')                                             AS station,
    NULLIF(service, '')                                             AS service,
    ST_Area(ST_Transform(geometry, 3857))::real                     AS area,
    ST_PointOnSurface(geometry)::geometry(Point, 4326)              AS geometry
FROM osm.osm_transportation_polygon
WHERE subclass IN ('station', 'bus_station', 'ferry_terminal', 'rest_area', 'services', 'platform');

CREATE INDEX idx_transportation_station_label_geometry ON export.transportation_station_label USING gist(geometry);
CREATE INDEX idx_transportation_station_label_osm_id   ON export.transportation_station_label USING btree(osm_id);
CREATE INDEX idx_transportation_station_label_name     ON export.transportation_station_label USING btree(name) WHERE name IS NOT NULL;
COMMIT;
