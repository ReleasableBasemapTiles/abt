-- =============================================================================
-- LAYER: Road
-- Schema:        export
-- Intermediates: transportation.usa_boundary
-- Sources:       osm.osm_highway_linestring
--                aux_data.fieldmaps_adm0_polygon
-- =============================================================================


-- -----------------------------------------------------------------------------
-- transportation — schema
-- -----------------------------------------------------------------------------

BEGIN;
CREATE SCHEMA IF NOT EXISTS transportation;
COMMIT;


-- -----------------------------------------------------------------------------
-- transportation.usa_boundary — USA boundary polygon (Natural Earth 1:10m)
-- -----------------------------------------------------------------------------

BEGIN;
DROP TABLE IF EXISTS transportation.usa_boundary CASCADE;
CREATE TABLE transportation.usa_boundary AS
SELECT
    'USA'                                                               AS gid_0,
    (ST_Dump(
        ST_MakeValid(geometry, 'method=structure')
    )).geom::geometry(Polygon, 4326)                                    AS geometry
FROM aux_data.ne_10m_admin_0_countries
WHERE iso_a3 = 'USA';

CREATE INDEX idx_usa_boundary_geometry ON transportation.usa_boundary USING gist(geometry);
CLUSTER transportation.usa_boundary USING idx_usa_boundary_geometry;
ANALYZE transportation.usa_boundary;
COMMIT;

-- -----------------------------------------------------------------------------
-- export.road_line — highway output layer
-- -----------------------------------------------------------------------------
BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.road_line CASCADE;

CREATE MATERIALIZED VIEW export.road_line AS
WITH highway_routes AS (
    -- One row per way: pick the most specific US route relation network.
    -- Priority: US:* interstate > US:us > US:<state> > other US:* > non-US
    SELECT DISTINCT ON (member)
        member                                                          AS osm_id,
        network,
        ref                                                             AS relation_ref
    FROM osm.osm_highway_relation
    WHERE route = 'road'
      AND NULLIF(TRIM(network), '') IS NOT NULL
    ORDER BY member,
        CASE
            WHEN network = 'US:interstate' THEN 1
            WHEN network = 'US:us'         THEN 2
            WHEN network LIKE 'US:%'       THEN 3
            ELSE 4
        END
),
highway_fieldmap AS (
    SELECT DISTINCT
        h.id,
        b.gid_0
    FROM osm.osm_highway_linestring h
    JOIN transportation.usa_boundary b
        ON h.geometry && b.geometry
       AND ST_Intersects(h.geometry, b.geometry)
    WHERE h.ref IS NOT NULL
      AND TRIM(h.ref) != ''
      AND h.subclass IN (
          'motorway', 'motorway_link', 'trunk', 'trunk_link',
          'primary', 'primary_link', 'secondary', 'secondary_link',
          'tertiary', 'tertiary_link'
      )
      AND h.geometry && (SELECT ST_Extent(geometry)::geometry FROM transportation.usa_boundary)
),
normalized AS (
    SELECT
        id,
        -- surface: simple regex alternation
        CASE
            WHEN surface IS NULL OR TRIM(surface) = '' THEN 'paved_unknown'
            WHEN lower(surface) ~ '(asphalt|asphal|asfalt|tarmac|concrete|cement|cobblestone|sett|paving_stone|brick|block|metal|steel|wood|boardwalk|chipseal|tiles|flagstone|bitum|interlock|paver|tartan|unhewn_cobblestone|pebblestone|\mpaved\M)'
                OR surface ~* 'tar.*road'                               THEN 'paved'
            WHEN lower(surface) ~ '(unpaved|dirt|gravel|sand|earth|mud|grass|ground|clay|soil|compacted|fine_gravel|ice|snow|shell|rock|stone)' THEN 'unpaved'
            ELSE 'unknown'
        END                                                             AS normalized_surface,
        CASE lower(subclass)
            WHEN 'construction' THEN COALESCE(NULLIF(TRIM(lower(construction)), ''), 'road')
            WHEN 'proposed'     THEN COALESCE(NULLIF(TRIM(lower(proposed)), ''), 'road')
            WHEN 'planned'      THEN COALESCE(NULLIF(TRIM(lower(planned)), ''), 'road')
            WHEN 'destroyed'    THEN COALESCE(NULLIF(TRIM(lower(destroyed_highway)), ''), 'road')
            WHEN 'demolished'   THEN COALESCE(NULLIF(TRIM(lower(tags->'demolished:highway')), ''), 'road')
            WHEN 'razed'        THEN COALESCE(NULLIF(TRIM(lower(tags->'razed:highway')), ''), 'road')
            WHEN 'removed'      THEN COALESCE(NULLIF(TRIM(lower(tags->'removed:highway')), ''), 'road')
            WHEN 'motorway'          THEN 'motorway'
            WHEN 'motoway'           THEN 'motorway'
            WHEN 'trunk'             THEN 'trunk'
            WHEN 'primary'           THEN 'primary'
            WHEN 'secondary'         THEN 'secondary'
            WHEN 'tertiary'          THEN 'tertiary'
            WHEN 'minor'             THEN 'tertiary'
            WHEN 'residential'       THEN 'residential'
            WHEN 'unclassified'      THEN 'unclassified'
            WHEN 'living_street'     THEN 'living_street'
            WHEN 'livingstreet'      THEN 'living_street'
            WHEN 'pedestrian'        THEN 'pedestrian'
            WHEN 'track'             THEN 'track'
            WHEN 'bus_guideway'      THEN 'bus_guideway'
            WHEN 'escape'            THEN 'escape'
            WHEN 'raceway'           THEN 'raceway'
            WHEN 'road'              THEN 'road'
            WHEN 'busway'            THEN 'busway'
            WHEN 'footway'           THEN 'footway'
            WHEN 'bridleway'         THEN 'bridleway'
            WHEN 'steps'             THEN 'steps'
            WHEN 'corridor'          THEN 'corridor'
            WHEN 'path'              THEN 'path'
            WHEN 'cycleway'          THEN 'cycleway'
            WHEN 'abandoned'         THEN 'abandoned'
            WHEN 'demolished'        THEN 'demolished'
            WHEN 'motorway_link'     THEN 'motorway_link'
            WHEN 'trunk_link'        THEN 'trunk_link'
            WHEN 'primary_link'      THEN 'primary_link'
            WHEN 'secondary_link'    THEN 'secondary_link'
            WHEN 'tertiary_link'     THEN 'tertiary_link'
            WHEN 'unclassified_link' THEN 'unclassified_link'
            ELSE lower(subclass)
        END                                                             AS normalized_subclass,
        -- ref: extract numeric portions inline
        CASE
            WHEN ref IS NOT NULL
            THEN NULLIF(
                (SELECT string_agg(m[1], ';') FROM regexp_matches(ref, '[0-9]+', 'g') AS m),
                ''
            )
        END                                                             AS ref_number
    FROM osm.osm_highway_linestring
    WHERE NOT is_area
),
base AS (
    SELECT
        h.osm_id,
        h.geometry,
        ST_Length(ST_Transform(h.geometry, 3857))::int                  AS geom_len,
        CASE
            WHEN h.is_tunnel THEN CASE WHEN h.is_bridge THEN 'tunnel;bridge' ELSE 'tunnel' END
            WHEN h.is_bridge THEN CASE WHEN h.is_ford THEN 'bridge;ford' ELSE 'bridge' END
            WHEN h.is_ford   THEN 'ford'
            WHEN NULLIF(TRIM(h.destroyed_bridge), '')         IS NOT NULL THEN 'bridge'
            WHEN NULLIF(h.tags->'destroyed:tunnel', '')        IS NOT NULL THEN 'tunnel'
        END                                                             AS brunnel,
        COALESCE(
            NULLIF(TRIM(h.bridge_name), ''), 
            NULLIF(TRIM(h.tunnel_name), '')
        )                                                               AS brunnel_name,
        n.normalized_subclass                                           AS subclass,
        h.name,
        h.name_en,
        length(h.name)                                                  AS name_len,
        NULLIF(TRIM(h.ref), '')                                         AS ref,
        length(h.ref)                                                   AS ref_len,
        n.ref_number,
        length(n.ref_number)                                            AS ref_number_len,
        COALESCE(h.ref ~~ ANY(ARRAY['%:%', '%,%', '%;%']), false)       AS ref_multi,
        h.network,
        COALESCE(hf.gid_0 = 'USA', false)
            OR hr.network LIKE 'US:%'
            OR h.network LIKE 'US:%'
            OR NULLIF(TRIM(h.ref), '') ~ '^(I |US |[A-Z]{2} )'         AS is_us,
        n.normalized_surface                                            AS surface,
        CASE
            WHEN lower(h.subclass) IN (
                'construction', 'proposed', 'planned', 'destroyed',
                'demolished', 'razed', 'removed', 'disused', 'abandoned'
            ) THEN lower(h.subclass)
            -- Pattern 1: highway=<class> + <lifecycle>:highway=<class> — detect via prefix tags
            WHEN NULLIF(TRIM(h.destroyed_highway), '') IS NOT NULL
              OR NULLIF(h.tags->'destroyed', '')        IS NOT NULL     THEN 'destroyed'
            WHEN NULLIF(h.tags->'demolished:highway', '') IS NOT NULL
              OR NULLIF(h.tags->'demolished', '')        IS NOT NULL    THEN 'demolished'
            WHEN NULLIF(h.tags->'razed:highway', '')    IS NOT NULL
              OR NULLIF(h.tags->'razed', '')             IS NOT NULL    THEN 'razed'
            WHEN NULLIF(h.tags->'removed:highway', '')  IS NOT NULL
              OR NULLIF(h.tags->'removed', '')           IS NOT NULL    THEN 'removed'
            ELSE 'intact'
        END                                                             AS lifecycle_type,
        CASE
            WHEN (hf.gid_0 = 'USA' OR hr.network LIKE 'US:%' OR h.network LIKE 'US:%'
                  OR NULLIF(TRIM(h.ref), '') ~ '^(I |US |[A-Z]{2} )')
                 AND NOT COALESCE(h.ref ~~ ANY(ARRAY['%:%', '%,%', '%;%']), false) THEN
                CASE
                    -- relation network fallback
                    WHEN hr.network = 'US:interstate'               THEN
                        CASE
                            WHEN h.ref ILIKE '%Bus%' THEN 'Interstate Business'
                            WHEN h.ref LIKE '% % %'  THEN 'Interstate Other'
                            ELSE                          'Interstate'
                        END
                    WHEN hr.network = 'US:us'                       THEN
                        CASE
                            WHEN h.ref LIKE '%Bus%'  THEN 'US Hwy Business'
                            WHEN h.ref LIKE '% % %'  THEN 'US Hwy Other'
                            ELSE                          'US Hwy'
                        END
                    WHEN hr.network LIKE 'US:%'                     THEN
                        CASE
                            WHEN h.ref LIKE '__ %Bus%' THEN 'State Hwy Business'
                            WHEN h.ref LIKE '__ % %'   THEN 'State Hwy Other'
                            ELSE                            'State Hwy'
                        END
                    -- ref pattern matching fallback
                    WHEN h.ref ~ '^(A[KLRZ]|C[AOT]|D[CE]|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[AT]|W[AIVY])' THEN
                        CASE
                            WHEN h.ref LIKE '__ %Bus%' THEN 'State Hwy Business'
                            WHEN h.ref LIKE '__ % %'   THEN 'State Hwy Other'
                            ELSE                            'State Hwy'
                        END
                    WHEN h.ref LIKE 'US %' THEN
                        CASE
                            WHEN h.ref LIKE '%Bus%'    THEN 'US Hwy Business'
                            WHEN h.ref LIKE '% % %'    THEN 'US Hwy Other'
                            ELSE                            'US Hwy'
                        END
                    WHEN h.ref LIKE 'I %' THEN
                        CASE
                            WHEN h.ref ILIKE '%Bus%'   THEN 'Interstate Business'
                            WHEN h.ref LIKE '% % %'    THEN 'Interstate Other'
                            ELSE                            'Interstate'
                        END
                    ELSE 'Other'
                END
            WHEN hf.gid_0 = 'USA' OR hr.network LIKE 'US:%' THEN 'Other'
            ELSE NULL
        END                                                             AS route_type,
        CASE
            WHEN h.lanes IN ('1','2','3','4','5') THEN h.lanes::int
            ELSE NULL
        END                                                             AS lane,
        h.layer,
        h.level,
        h.service,
        h.access,
        h.toll,
        h.expressway,
        h.bicycle,
        h.foot,
        h.horse,
        h.is_oneway,
        h.is_ramp
    FROM osm.osm_highway_linestring h
    LEFT JOIN normalized n          ON h.id = n.id
    LEFT JOIN highway_fieldmap hf   ON h.id = hf.id
    LEFT JOIN highway_routes hr     ON h.osm_id = hr.osm_id
    WHERE NOT h.is_area
)
SELECT * FROM base
WHERE geometry IS NOT NULL 
  AND subclass IN (
      'demolished', 'abandoned', 'bridleway','bus_guideway','cycleway','footway',
      'living_street','motorway','motorway_link','path','pedestrian','primary',
      'primary_link','raceway','residential','road','secondary','secondary_link',
      'service','steps','tertiary','tertiary_link','track','trunk','trunk_link',
      'unclassified',''
  );

CREATE INDEX idx_road_line_geometry ON export.road_line USING gist(geometry);
CREATE UNIQUE INDEX idx_road_line_osm_id ON export.road_line USING btree(osm_id);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.road_polygon — highway polygon features (pedestrian areas, platforms, etc.)
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.road_polygon CASCADE;
CREATE MATERIALIZED VIEW export.road_polygon AS
SELECT
    osm_id,
    NULLIF(name, '')                                                    AS name,
    NULLIF(name_en, '')                                                 AS name_en,
    subclass,
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area,
    geometry
FROM osm.osm_highway_polygon
WHERE class = 'highway'
  AND subclass IN ('pedestrian', 'footway', 'steps', 'path', 'cycleway', 'bridleway', 'corridor')
  AND geometry IS NOT NULL

UNION ALL

SELECT
    osm_id,
    NULLIF(name, '')                                                    AS name,
    NULLIF(name_en, '')                                                 AS name_en,
    'platform'::text                                                    AS subclass,
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area,
    geometry
FROM osm.osm_highway_polygon
WHERE class = 'public_transport'
  AND subclass = 'platform'
  AND geometry IS NOT NULL;

CREATE INDEX idx_road_polygon_geometry ON export.road_polygon USING gist(geometry);
CREATE INDEX idx_road_polygon_subclass ON export.road_polygon USING btree(subclass);
COMMIT;
