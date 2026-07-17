-- =============================================================================
-- LAYER: Energy / Extraction
-- Schema:        export
-- Intermediates: infrastructure.energy_field
-- Sources:       osm.osm_utility_polygon, osm.osm_landuse_polygon,
--                osm.osm_utility_point
-- =============================================================================


-- -----------------------------------------------------------------------------
-- infrastructure.energy_field — classified oil/gas facility polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS infrastructure.energy_field CASCADE;
CREATE MATERIALIZED VIEW infrastructure.energy_field AS
WITH classified AS (
    SELECT
        id,
        osm_id,
        class,
        CASE
            WHEN subclass IN ('oil','wellsite','storage_tank') AND (
                name % 'terminal'
                OR name % 'storage'
                OR name % 'depot'
                OR name % 'farm'
            ) THEN 'oil_terminal'
            WHEN subclass IN ('oil','wellsite','storage_tank') AND (
                name % 'refinery'
                OR name % 'facility'
                OR name % 'plant'
            ) THEN 'oil_refinery'
            WHEN subclass IN ('oil','wellsite') AND name % 'station' THEN 'station'
            WHEN subclass = 'wellsite' AND (
                name % 'area'
                OR name % 'field'
            ) THEN 'oilfield'
            WHEN subclass IN ('oil_terminal', 'oil_refinery', 'oilfield') THEN subclass
            WHEN subclass = 'storage_tank' AND content = 'oil' THEN 'oil_storage'
            ELSE subclass
        END                                                             AS subclass,
        NULLIF(name, '')                                                AS name,
        NULLIF(name_en, '')                                             AS name_en,
        NULLIF(operator, '')                                            AS operator,
        COALESCE(
            substance,
            CASE
                WHEN tags -> 'type' ILIKE '%oil%' THEN tags -> 'type'
                WHEN tags -> 'content' IS NOT NULL THEN tags -> 'content'
                ELSE NULL
            END
        )                                                               AS substance,
        tags -> 'ref'                                                   AS ref,
        tags -> 'access'                                                AS access,
        tags -> 'type'                                                  AS type,
        content,
        ST_Area(ST_Transform(geometry, 3857))::real                     AS area,
        tags,
        geometry
    FROM osm.osm_utility_polygon
    WHERE subclass IN ('oil', 'wellsite', 'oilfield', 'oil_terminal', 'oil_refinery', 'refinery')
       OR (subclass = 'storage_tank' AND content IN ('oil', 'gas', 'fuel'))
       OR name % 'oil'
       OR name % 'refinery'
       OR name % 'terminal'
       OR (tags -> 'content') % 'oil'
       OR (tags -> 'type') % 'oil'

    UNION ALL

    -- landuse=industrial with industrial=oil/oilfield/wellsite
    SELECT
        id,
        osm_id,
        class,
        CASE
            WHEN industrial IN ('oil_refinery', 'refinery') THEN 'oil_refinery'
            WHEN industrial IN ('oil_terminal', 'terminal') THEN 'oil_terminal'
            WHEN industrial IN ('oilfield', 'wellsite')     THEN 'oilfield'
            ELSE 'oilfield'
        END                                                             AS subclass,
        NULLIF(name, '')                                                AS name,
        NULLIF(name_en, '')                                             AS name_en,
        NULLIF(tags -> 'operator', '')                                  AS operator,
        NULL::text                                                      AS substance,
        tags -> 'ref'                                                   AS ref,
        access,
        tags -> 'type'                                                  AS type,
        NULL::text                                                      AS content,
        ST_Area(ST_Transform(geometry, 3857))::real                     AS area,
        tags,
        geometry
    FROM osm.osm_landuse_polygon
    WHERE industrial IN ('oil', 'oilfield', 'oil_refinery', 'refinery', 'oil_terminal', 'wellsite')
)
SELECT
    id,
    osm_id,
    class,
    subclass,
    name,
    name_en,
    operator,
    substance,
    ref,
    access,
    type,
    area,
    geometry
FROM classified
WHERE NOT (
    subclass IN ('oil', 'wellsite')
    AND name IS NULL
    AND ref IS NULL
    AND (
        area < 1000000
        OR (area < 2000000 AND operator IS NULL)
    )
);

CREATE INDEX idx_energy_field_geometry ON infrastructure.energy_field USING gist(geometry);
CREATE INDEX idx_energy_field_osm_id   ON infrastructure.energy_field USING btree(osm_id);
CREATE INDEX idx_energy_field_subclass ON infrastructure.energy_field USING btree(subclass);
CREATE INDEX idx_energy_field_area     ON infrastructure.energy_field USING btree(area);
CREATE INDEX idx_energy_field_name     ON infrastructure.energy_field USING btree(name) WHERE name IS NOT NULL;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.energy_polygon — energy/hydrocarbon field polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.energy_polygon CASCADE;
CREATE MATERIALIZED VIEW export.energy_polygon AS
SELECT * FROM infrastructure.energy_field;

CREATE INDEX idx_energy_polygon_geometry ON export.energy_polygon USING gist(geometry);
CREATE INDEX idx_energy_polygon_osm_id   ON export.energy_polygon USING btree(osm_id);
CREATE INDEX idx_energy_polygon_subclass ON export.energy_polygon USING btree(subclass);
CREATE INDEX idx_energy_polygon_area     ON export.energy_polygon USING btree(area);
CREATE INDEX idx_energy_polygon_name     ON export.energy_polygon USING btree(name) WHERE name IS NOT NULL;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.energy_label — label points for energy fields and mineshafts
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.energy_label CASCADE;
CREATE MATERIALIZED VIEW export.energy_label AS

-- Hydrocarbon field label points
SELECT
    osm_id,
    subclass,
    name,
    name_en,
    operator,
    substance,
    NULL::text                                                          AS resource,
    NULL::text                                                          AS mineshaft_type,
    NULL::boolean                                                       AS disused,
    area,
    ST_PointOnSurface(geometry)::geometry(Point, 4326)                  AS geometry
FROM infrastructure.energy_field
WHERE name IS NOT NULL
   OR ref IS NOT NULL
   OR (area > 5000000 AND operator IS NOT NULL)

UNION ALL

-- Mineshaft points
SELECT
    osm_id,
    'mineshaft'::text                                                   AS subclass,
    NULLIF(name, '')                                                    AS name,
    NULLIF(name_en, '')                                                 AS name_en,
    NULLIF(operator, '')                                                AS operator,
    NULL::text                                                          AS substance,
    NULLIF(resource, '')                                                AS resource,
    NULLIF(mineshaft_type, '')                                          AS mineshaft_type,
    CASE WHEN disused THEN true ELSE NULL END                           AS disused,
    NULL::real                                                          AS area,
    geometry
FROM osm.osm_utility_point
WHERE subclass = 'mineshaft';

CREATE INDEX idx_energy_label_geometry ON export.energy_label USING gist(geometry);
CREATE INDEX idx_energy_label_osm_id   ON export.energy_label USING btree(osm_id);
CREATE INDEX idx_energy_label_subclass ON export.energy_label USING btree(subclass);
CREATE INDEX idx_energy_label_name     ON export.energy_label USING btree(name) WHERE name IS NOT NULL;
COMMIT;
