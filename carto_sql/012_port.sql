-- =============================================================================
-- LAYER: Port
-- Schema:        export
-- Intermediates: infrastructure.port_surface_enhanced
-- Sources:       osm.osm_builtup_area
-- =============================================================================


-- -----------------------------------------------------------------------------
-- SCHEMA
-- -----------------------------------------------------------------------------

BEGIN;
CREATE SCHEMA IF NOT EXISTS infrastructure;
COMMIT;


-- -----------------------------------------------------------------------------
-- infrastructure.port_surface_enhanced — clustered, ranked port polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS infrastructure.port_surface_enhanced CASCADE;
CREATE MATERIALIZED VIEW infrastructure.port_surface_enhanced AS
WITH base_ports AS (
    SELECT
        b.osm_id,
        NULLIF(b.name, '')                                              AS name,
        b.class,
        b.subclass,
        NULLIF(b.industrial, '')                                        AS industrial,
        NULLIF(b.port, '')                                              AS port,
        NULLIF(b.cargo, '')                                             AS cargo,
        NULLIF(b.access, '')                                            AS access,
        NULLIF(b.port_type, '')                                         AS port_type,
        ST_Area(ST_Transform(b.geometry, 3857))::real                   AS area,
        (ST_Dump(
            ST_CollectionExtract(ST_MakeValid(b.geometry), 3)
        )).geom::geometry(Polygon, 4326)                                AS geometry
    FROM osm.osm_builtup_area AS b
    WHERE (b.subclass IN ('port', 'harbour'))
       OR (b.subclass = 'industrial' AND b.industrial = 'port')
),
ports_with_fid AS (
    SELECT
        ROW_NUMBER() OVER (ORDER BY osm_id, area DESC)                  AS fid,
        ST_Area(ST_Transform(geometry, 3857))::real                     AS area_part,
        *
    FROM base_ports
),
ranked_ports AS (
    SELECT
        *,
        RANK() OVER (PARTITION BY osm_id ORDER BY area_part DESC)       AS rank_value
    FROM ports_with_fid
),
ports_with_overlap AS (
    SELECT
        a.*,
        CASE
            WHEN a.rank_value = 1 THEN 1
            ELSE 0
        END                                                             AS rank,
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM ranked_ports b
                WHERE ST_Overlaps(b.geometry, a.geometry)
                  AND a.fid != b.fid
            ) THEN 1
            ELSE 0
        END                                                             AS overlap,
        -- contained: ≥95% of this feature's area lies within a larger
        -- feature. An area-fraction test instead of ST_Contains/
        -- ST_ContainsProperly: OSM way-vs-relation boundaries misalign by
        -- slivers, so morally-contained features fail binary DE-9IM
        -- predicates (e.g. 99.8% inside still reports ST_Overlaps).
        -- The fid tiebreak keeps one of two exact duplicates visible.
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM ranked_ports b
                WHERE a.fid != b.fid
                  AND (b.area_part > a.area_part
                       OR (b.area_part = a.area_part AND b.fid < a.fid))
                  AND a.geometry && b.geometry
                  AND ST_Area(ST_Intersection(a.geometry, b.geometry))
                      >= 0.95 * ST_Area(a.geometry)
            ) THEN 1
            ELSE 0
        END                                                             AS contained
    FROM ranked_ports a
)
SELECT * FROM ports_with_overlap
ORDER BY osm_id, area DESC;

CREATE INDEX idx_port_surface_enhanced_geometry ON infrastructure.port_surface_enhanced USING gist(geometry);
CREATE INDEX idx_port_surface_enhanced_osm_id   ON infrastructure.port_surface_enhanced USING btree(osm_id);
CREATE INDEX idx_port_surface_enhanced_subclass ON infrastructure.port_surface_enhanced USING btree(subclass);
CREATE INDEX idx_port_surface_enhanced_rank     ON infrastructure.port_surface_enhanced USING btree(rank);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.port_polygon — port polygon output layer
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.port_polygon CASCADE;
CREATE MATERIALIZED VIEW export.port_polygon AS
SELECT * FROM infrastructure.port_surface_enhanced;

CREATE INDEX idx_port_surface_geometry ON export.port_polygon USING gist(geometry);
CREATE INDEX idx_port_surface_osm_id   ON export.port_polygon USING btree(osm_id);
CREATE INDEX idx_port_surface_subclass ON export.port_polygon USING btree(subclass);
CREATE INDEX idx_port_surface_rank     ON export.port_polygon USING btree(rank);
CREATE INDEX idx_port_surface_name     ON export.port_polygon USING btree(name) WHERE name IS NOT NULL;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.port_label — label points for port polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.port_label CASCADE;
CREATE MATERIALIZED VIEW export.port_label AS
SELECT
    osm_id,
    name,
    class,
    subclass,
    industrial,
    port,
    cargo,
    access,
    port_type,
    area,
    area_part,
    NULLIF(rank, 0)                                                     AS rank,
    overlap,
    NULLIF(contained, 0)                                                AS contained,
    ST_PointOnSurface(geometry)::geometry(Point, 4326)                  AS geometry
FROM infrastructure.port_surface_enhanced;

CREATE INDEX idx_port_label_geometry ON export.port_label USING gist(geometry);
CREATE INDEX idx_port_label_osm_id   ON export.port_label USING btree(osm_id);
CREATE INDEX idx_port_label_subclass ON export.port_label USING btree(subclass);
CREATE INDEX idx_port_label_rank     ON export.port_label USING btree(rank);
CREATE INDEX idx_port_label_name     ON export.port_label USING btree(name) WHERE name IS NOT NULL;
COMMIT;
