-- =============================================================================
-- LAYER: Water — Polygons
-- Schema:        export
-- Intermediates: water.water_surface
--                water.water_surface_clean
--                water.valid_ocean
-- Sources:       osm.osm_water_polygon
--                aux_data.osm_ocean
--                aux_data.ne_50m_ocean
--                aux_data.ne_50m_lakes
-- =============================================================================


-- -----------------------------------------------------------------------------
-- SCHEMA
-- -----------------------------------------------------------------------------

BEGIN;
CREATE SCHEMA IF NOT EXISTS water;
COMMIT;


-- -----------------------------------------------------------------------------
-- water.classify_water_type — normalises raw OSM subclass strings to a
--                              controlled water-type vocabulary
-- -----------------------------------------------------------------------------

BEGIN;
CREATE OR REPLACE FUNCTION water.classify_water_type(subclass_input text)
RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
AS $$
BEGIN
    IF subclass_input IS NULL OR subclass_input = '' THEN
        RETURN 'water';
    END IF;

    RETURN CASE
        WHEN subclass_input ~ '^bas'          THEN 'basin'
        WHEN subclass_input ~ 'bayou'         THEN 'bayou'
        WHEN subclass_input ~ 'can[ao]l'      THEN 'canal'
        WHEN subclass_input ~ 'lake'          THEN 'lake'
        WHEN subclass_input ~ 'pool'          THEN 'pool'
        WHEN subclass_input ~ 'pond'          THEN 'pond'
        WHEN subclass_input ~ 'res[eo]rvoir'  THEN 'reservoir'
        WHEN subclass_input ~ 'cove'          THEN 'cove'
        WHEN subclass_input ~ 'creek'         THEN 'creek'
        WHEN subclass_input ~ 'spring'        THEN 'spring'
        WHEN subclass_input ~ 'river'         THEN 'river'
        WHEN subclass_input ~ 'ditch'         THEN 'ditch'
        WHEN subclass_input ~ 'stream'        THEN 'stream'
        WHEN subclass_input ~ '^est'          THEN 'estuary'
        WHEN subclass_input ~ 'fall'          THEN 'falls'
        WHEN subclass_input ~ '^fj[oi]'       THEN 'fjord'
        WHEN subclass_input ~ '^ha[rv]bou?r'  THEN 'harbour'
        WHEN subclass_input ~ 'lag[ou]'       THEN 'lagoon'
        WHEN subclass_input ~ 'ocean'         THEN 'ocean'
        WHEN subclass_input ~ '^rapi'         THEN 'rapids'
        WHEN subclass_input ~ 'o[xs]bow'      THEN 'oxbow'
        WHEN subclass_input ~ '^tidal'        THEN 'tidal'
        WHEN subclass_input ~ '^waste'        THEN 'wastewater'
        WHEN subclass_input = 'yes'           THEN 'water'
        ELSE subclass_input
    END;
END;
$$;
COMMIT;


-- -----------------------------------------------------------------------------
-- water.safe_simplify_geometry — validates geometry before simplification;
--                                 returns original on unexpected error
-- -----------------------------------------------------------------------------

BEGIN;
CREATE OR REPLACE FUNCTION water.safe_simplify_geometry(geom geometry, tolerance float8)
RETURNS geometry
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL UNSAFE
AS $$
BEGIN
    IF NOT ST_IsValid(geom) THEN
        geom := ST_MakeValid(geom, 'method=structure');
    END IF;
    RETURN ST_SimplifyPreserveTopology(geom, tolerance);
EXCEPTION WHEN OTHERS THEN
    RETURN geom;
END;
$$;
COMMIT;


-- -----------------------------------------------------------------------------
-- water.water_surface — classified, simplified permanent water polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS water.water_surface CASCADE;
CREATE MATERIALIZED VIEW water.water_surface AS
WITH water_classified AS (
    SELECT
        osm_id,
        NULLIF(name, '')                                        AS name,
        NULLIF(name_en, '')                                     AS name_en,
        water.classify_water_type(subclass)                     AS subclass,
        ST_Area(ST_Transform(geometry, 3857))::real             AS area,
        water.safe_simplify_geometry(geometry, 0.000001)        AS geometry,
        intermittent
    FROM osm.osm_water_polygon
    WHERE intermittent = 'f'
      AND geometry IS NOT NULL
)
SELECT
    osm_id,
    name,
    name_en,
    subclass,
    intermittent,
    area,
    geometry
FROM water_classified
WHERE subclass IN (
    'artificial', 'basin', 'bay', 'bayou', 'brook', 'canal', 'cenote',
    'channel', 'connector', 'canoe_pass', 'cove', 'creek', 'derelict_canal',
    'disused_canal', 'ditch', 'drain', 'estuary', 'falls', 'fish_pass',
    'fishpond', 'fjord', 'glacial_lage', 'guelta', 'gulf', 'harbour',
    'lagoon', 'lake', 'lake;pond', 'lake;reservoir', 'moat', 'ocean',
    'old_river', 'oxbow', 'pan', 'piscina', 'pond', 'pond;reservoir',
    'pool', 'rapids', 'reservoir', 'river', 'river;canal', 'riverbank',
    'riverbed', 'salt_pond', 'sea', 'sound', 'spillway', 'spring',
    'swimming_pool', 'strait', 'stream', 'stream_pool', 'stream;river',
    'tidal', 'tidal_channel', 'unclassified', 'wastewater', 'water',
    'waterfall', 'yes'
)
  AND geometry IS NOT NULL;

CREATE INDEX idx_water_surface_geometry ON water.water_surface USING gist(geometry);
CREATE INDEX idx_water_surface_osm_id   ON water.water_surface USING btree(osm_id);
CREATE INDEX idx_water_surface_subclass ON water.water_surface USING btree(subclass);
CREATE INDEX idx_water_surface_area     ON water.water_surface USING btree(area);
CREATE INDEX idx_water_surface_name     ON water.water_surface USING btree(name) WHERE name IS NOT NULL;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.inland_water_intermittent_polygon — seasonal / intermittent water polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.inland_water_intermittent_polygon CASCADE;
CREATE MATERIALIZED VIEW export.inland_water_intermittent_polygon AS
WITH intermittent_water AS (
    SELECT
        osm_id,
        NULLIF(name, '')                                            AS name,
        NULLIF(name_en, '')                                         AS name_en,
        water.classify_water_type(subclass)                         AS subclass,
        (ST_Dump(
            ST_MakeValid(
                ST_SimplifyPreserveTopology(geometry, 0.000001),
                'method=structure'
            )
        )).geom::geometry(Polygon, 4326)                            AS geometry,
        ST_Area(ST_Transform(geometry, 3857))::real                 AS area,
        intermittent
    FROM osm.osm_water_polygon
    WHERE (intermittent = 't' OR subclass IN ('intermittent', 'seasonal', 'drystream'))
      AND geometry IS NOT NULL
)
SELECT * FROM intermittent_water;

CREATE INDEX idx_inland_water_intermittent_geometry ON export.inland_water_intermittent_polygon USING gist(geometry);
CREATE INDEX idx_inland_water_intermittent_osm_id   ON export.inland_water_intermittent_polygon USING btree(osm_id);
CREATE INDEX idx_inland_water_intermittent_subclass ON export.inland_water_intermittent_polygon USING btree(subclass);
CREATE INDEX idx_inland_water_intermittent_area     ON export.inland_water_intermittent_polygon USING btree(area);
CREATE INDEX idx_inland_water_intermittent_name     ON export.inland_water_intermittent_polygon USING btree(name) WHERE name IS NOT NULL;
COMMIT;


-- -----------------------------------------------------------------------------
-- water.water_surface_clean — exploded single polygons, marine types excluded
-- -----------------------------------------------------------------------------

BEGIN;
DROP TABLE IF EXISTS water.water_surface_clean CASCADE;
CREATE TABLE water.water_surface_clean AS
SELECT
    subclass,
    (ST_Dump(ST_MakeValid(ST_Union(geometry), 'method=structure'))).geom::geometry(Polygon, 4326) AS geometry
FROM (
    SELECT
        subclass,
        ST_ClusterDBSCAN(geometry, eps := 0.000001, minpoints := 1) OVER (PARTITION BY subclass) AS cid,
        ST_MakeValid(
            ST_SimplifyPreserveTopology(geometry, 0.000001),
            'method=structure'
        ) AS geometry
    FROM water.water_surface
    WHERE subclass NOT IN ('bay', 'harbour', 'sea', 'strait')
) clustered
GROUP BY subclass, cid;

CREATE INDEX idx_water_surface_clean_geometry ON water.water_surface_clean USING gist(geometry);
CREATE INDEX idx_water_surface_clean_subclass ON water.water_surface_clean USING btree(subclass);
COMMIT;


-- -----------------------------------------------------------------------------
-- water.valid_ocean — validated, exploded ocean polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP TABLE IF EXISTS water.valid_ocean CASCADE;
CREATE TABLE water.valid_ocean AS
SELECT
    'ocean'                                                         AS subclass,
    (ST_Dump(
        ST_SimplifyPreserveTopology(
            ST_MakeValid(geometry, 'method=structure'),
            0.000001
        )
    )).geom::geometry(Polygon, 4326)                                AS geometry
FROM aux_data.osm_ocean
WHERE geometry IS NOT NULL
  AND NOT ST_IsEmpty(geometry);

CREATE INDEX idx_valid_ocean_geometry ON water.valid_ocean USING gist(geometry);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.ocean_polygon — ocean polygons with NE/OSM zoom transition
-- export.water_polygon — inland water polygons (NE 50m lakes + OSM)
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.ocean_polygon CASCADE;
CREATE MATERIALIZED VIEW export.ocean_polygon AS

SELECT
    'ocean'::text                                                    AS subclass,
    ST_MakeValid(
        (ST_Dump(geometry)).geom::geometry(Polygon, 4326),
        'method=structure'
    )                                                                AS geometry,
    0                                                                AS z_level
FROM aux_data.ne_50m_ocean
WHERE geometry IS NOT NULL
  AND NOT ST_IsEmpty(geometry)

UNION ALL

SELECT
    subclass::text,
    ST_MakeValid(geometry, 'method=structure')                       AS geometry,
    1                                                                AS z_level
FROM water.valid_ocean;

CREATE INDEX idx_ocean_geometry         ON export.ocean_polygon USING gist(geometry);
CREATE INDEX idx_ocean_polygon_z_level  ON export.ocean_polygon USING btree(z_level);
COMMIT;

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.water_polygon CASCADE;
CREATE MATERIALIZED VIEW export.water_polygon AS

SELECT
    'lake'::text                                                    AS subclass,
    ST_MakeValid(
        (ST_Dump(geometry)).geom::geometry(Polygon, 4326),
        'method=structure'
    )                                                               AS geometry,
    1                                                               AS z_level
FROM aux_data.ne_50m_lakes
WHERE geometry IS NOT NULL
  AND NOT ST_IsEmpty(geometry)

UNION ALL

SELECT
    subclass::text,
    ST_MakeValid(geometry, 'method=structure')                      AS geometry,
    CASE
        WHEN ST_Area(geometry::geography) >= POWER(zres(5), 2) THEN 5
        WHEN ST_Area(geometry::geography) >= POWER(zres(6), 2) THEN 6
        WHEN ST_Area(geometry::geography) >= POWER(zres(7), 2) THEN 7
        WHEN ST_Area(geometry::geography) >= POWER(zres(8), 2) THEN 8
        WHEN ST_Area(geometry::geography) >= POWER(zres(9), 2) THEN 9
        WHEN ST_Area(geometry::geography) >= POWER(zres(10), 2) THEN 10
        WHEN ST_Area(geometry::geography) >= POWER(zres(11), 2) THEN 11
        ELSE 12
    END                                                             AS z_level
FROM water.water_surface_clean
WHERE geometry IS NOT NULL
  AND NOT ST_IsEmpty(geometry);

CREATE INDEX idx_water_geometry ON export.water_polygon USING gist(geometry);
CREATE INDEX idx_water_subclass ON export.water_polygon USING btree(subclass);
CREATE INDEX idx_water_z_level  ON export.water_polygon USING btree(z_level);
COMMIT;

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.ne_water_label CASCADE;
COMMIT;
