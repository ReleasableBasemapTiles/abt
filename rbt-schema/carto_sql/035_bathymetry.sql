-- =============================================================================
-- LAYER: Bathymetry
-- Schema:        export
-- Intermediates: water.bathymetry_depth
-- Sources:       aux_data.ne_10m_bathymetry_k_200
--                aux_data.ne_10m_bathymetry_j_1000
--                aux_data.ne_10m_bathymetry_i_2000
--                aux_data.ne_10m_bathymetry_h_3000
--                aux_data.ne_10m_bathymetry_g_4000
--                aux_data.ne_10m_bathymetry_f_5000
--                aux_data.ne_10m_bathymetry_e_6000
--                aux_data.ne_10m_bathymetry_d_7000
--                aux_data.ne_10m_bathymetry_c_8000
--                aux_data.ne_10m_bathymetry_b_9000
--                aux_data.ne_10m_bathymetry_a_10000
-- =============================================================================


-- -----------------------------------------------------------------------------
-- SCHEMA
-- -----------------------------------------------------------------------------

BEGIN;
CREATE SCHEMA IF NOT EXISTS water;
COMMIT;


-- -----------------------------------------------------------------------------
-- water.bathymetry_depth — one dissolved polygon per Natural Earth depth
--
-- Each Natural Earth file covers everything deeper than its depth, so the
-- files overlap: the 3000 m polygon lies inside the 2000 m one, and so on.
-- (Not exactly: a deeper file pokes outside the next shallower one by up to
-- 0.04% of its area, measured on release 4.1.0. The bands below ignore that
-- slop.) Some source polygons are invalid, hence ST_MakeValid.
--
-- The 0 m file (L_0) is not loaded. Its outer edge is Natural Earth's 1:10m
-- coastline, up to ~1 km off the OSM coastline ocean_polygon uses, so the
-- 0–200 m band would bleed onto land or leave slivers at z7–z8. The shelf
-- shows the ocean_polygon fill instead.
-- -----------------------------------------------------------------------------

BEGIN;
DROP TABLE IF EXISTS water.bathymetry_depth CASCADE;
CREATE TABLE water.bathymetry_depth AS
SELECT
    depth,
    ST_Union(ST_MakeValid(geometry))::geometry(Geometry, 4326) AS geometry
FROM (
    SELECT depth, geometry FROM aux_data.ne_10m_bathymetry_k_200
    UNION ALL SELECT depth, geometry FROM aux_data.ne_10m_bathymetry_j_1000
    UNION ALL SELECT depth, geometry FROM aux_data.ne_10m_bathymetry_i_2000
    UNION ALL SELECT depth, geometry FROM aux_data.ne_10m_bathymetry_h_3000
    UNION ALL SELECT depth, geometry FROM aux_data.ne_10m_bathymetry_g_4000
    UNION ALL SELECT depth, geometry FROM aux_data.ne_10m_bathymetry_f_5000
    UNION ALL SELECT depth, geometry FROM aux_data.ne_10m_bathymetry_e_6000
    UNION ALL SELECT depth, geometry FROM aux_data.ne_10m_bathymetry_d_7000
    UNION ALL SELECT depth, geometry FROM aux_data.ne_10m_bathymetry_c_8000
    UNION ALL SELECT depth, geometry FROM aux_data.ne_10m_bathymetry_b_9000
    UNION ALL SELECT depth, geometry FROM aux_data.ne_10m_bathymetry_a_10000
) src
WHERE geometry IS NOT NULL
GROUP BY depth;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.bathymetry_polygon — non-overlapping depth bands
--
-- Each band is its depth's polygon minus the next deeper one, so a style
-- needs one fill layer stepped on depth, and draw order within the layer
-- doesn't matter (stacked overlapping fills would, and tippecanoe's --hilbert
-- reorders features). depth_max is NULL for the deepest band (10000 m).
-- Subdivided to ≤1024 vertices like ocean_polygon: the 3000–5000 m bands are
-- single multipolygons of ~900k vertices each.
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.bathymetry_polygon CASCADE;
CREATE MATERIALIZED VIEW export.bathymetry_polygon AS
WITH bands AS (
    SELECT
        s.depth,
        d.depth AS depth_max,
        CASE WHEN d.geometry IS NULL THEN s.geometry
             ELSE ST_Difference(s.geometry, d.geometry)
        END AS geometry
    FROM water.bathymetry_depth s
    LEFT JOIN LATERAL (
        SELECT depth, geometry
        FROM water.bathymetry_depth n
        WHERE n.depth > s.depth
        ORDER BY n.depth
        LIMIT 1
    ) d ON true
)
SELECT
    b.depth::int                                                    AS depth,
    b.depth_max::int                                                AS depth_max,
    p.geom::geometry(Polygon, 4326)                                 AS geometry
FROM bands b,
LATERAL ST_Subdivide(ST_CollectionExtract(ST_MakeValid(b.geometry), 3), 1024) AS sub(geom),
LATERAL ST_Dump(sub.geom) AS p
WHERE NOT ST_IsEmpty(p.geom);

CREATE INDEX idx_bathymetry_polygon_geometry ON export.bathymetry_polygon USING gist (geometry);
COMMIT;
