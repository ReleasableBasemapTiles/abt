-- =============================================================================
-- LAYER: Populated Place Labels
-- Schema:        export
-- Source layer:  populated_places
-- Sources:       osm.osm_city_point
--                aux_data.nga_geonames_populated_places
--                aux_data.ne_10m_populated_places
--
--
-- METHODOLOGY (Data Sources in Priority Order):
--
-- 1. GeoNames (Highest Priority):
--    Establishes top-tier administrative status (like national capitals) by 
--    matching OSM places to GeoNames records. Resolves local-script names 
--    via variant matches.
--
-- 2. Natural Earth (Middle Priority):
--    Provides a curated cartographic score to differentiate broad categories. 
--    Ensures globally prominent non-capitals rank high, while separating 
--    large cities from small towns.
--
-- 3. OpenStreetMap / OSM (Lowest Priority / Fallback):
--    Uses standard OSM tags (city, town, village, hamlet) to efficiently rank 
--    smaller features that fall through the first two checks.
--
-- RANKING SCALE (1-12):
--    Ranks 1-2   : Global megacities and national capitals.
--    Rank 3      : Major state, provincial, or regional capitals.
--    Ranks 4-8   : Medium-to-large cities graded by cartographic prominence.
--    Ranks 9-10  : Small cities and towns.
--    Ranks 11-12 : Villages, hamlets, and minor points.

-- -----------------------------------------------------------------------------
-- Source table indexes (idempotent — safe to rerun)
-- -----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_geonames_pp_geometry
    ON aux_data.nga_geonames_populated_places USING gist(geometry);

CREATE INDEX IF NOT EXISTS idx_geonames_pp_ufi
    ON aux_data.nga_geonames_populated_places (ufi);

CREATE INDEX IF NOT EXISTS idx_geonames_pp_name
    ON aux_data.nga_geonames_populated_places (lower(full_nm_nd));

CREATE INDEX IF NOT EXISTS idx_geonames_pp_ufi_rank
    ON aux_data.nga_geonames_populated_places (ufi, name_rank, nt);


-- -----------------------------------------------------------------------------
-- export.place_labels
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.place_labels CASCADE;
CREATE MATERIALIZED VIEW export.place_labels AS

-- Cities and towns: full three-source ranking via GeoNames + NE + OSM fallback
SELECT
    o.osm_id,
    NULLIF(o.name, '')                                                  AS name,
    NULLIF(o.name_en, '')                                               AS name_en,
    o.place                                                             AS class,
    CASE o.place
        WHEN 'city'    THEN 1
        WHEN 'town'    THEN 2
        ELSE                3
    END                                                                 AS class_rank,
    CASE
        WHEN o.name_en = 'Taipei'               THEN NULL  -- DOS Bulletin 37: Taipei must not be symbolized as capital of a sovereign state
        -- DOS-directed primary capital override: Bujumbura remains primary per US State Dept
        WHEN o.osm_id = 60715062               THEN 2   -- Bujumbura (Burundi)
        -- Secondary national capitals (de facto, seat of government, legislative, judicial)
        WHEN o.osm_id IN (
              235857686,   -- The Hague (Netherlands)
              266478791,   -- La Paz (Bolivia)
             1046100133,   -- Abidjan (Côte d'Ivoire)
             2872238032,   -- Putrajaya (Malaysia)
               26576175,   -- Yangon (Myanmar)
              313764484,   -- Sucre (Bolivia)
               32675806,   -- Cape Town (South Africa)
               26938845,   -- Bloemfontein (South Africa)
              301351574,   -- Gitega (Burundi)
               50794342,   -- Colombo (Sri Lanka)
             4415037938    -- Lobamba (Eswatini)
        )                                       THEN 3
        WHEN o.capital = 'yes'                  THEN 2
        WHEN o.capital IN ('2','3','5','6')     THEN o.capital::int
        WHEN o.capital = '4'                    THEN 3
    END                                                                 AS capital,
    COALESCE(
        CASE
            WHEN o.name_en = 'Taipei'                                    THEN 1  -- DOS Bulletin 37: capital suppressed but prominence preserved
            WHEN ne.rank_max >= 14                                       THEN 1
            WHEN g.desig_cd = 'PPLC' AND ne.rank_max >= 13               THEN 1
            WHEN ne.rank_max = 13                                        THEN 2
            WHEN g.desig_cd = 'PPLC'                                     THEN 2
            WHEN o.capital = 'yes'                                       THEN 2
            WHEN o.name_en ILIKE 'Brussels'                              THEN 2
            WHEN o.capital::text = '3'
                AND ne.rank_max >= 11                                    THEN 3
            WHEN ne.rank_max = 12 AND ne.pop_max >= 3000000
                AND o.name_en NOT ILIKE 'Irvine'                          THEN 2
            WHEN ne.rank_max = 12 AND ne.pop_max >= 1500000
                AND o.name_en NOT ILIKE 'Irvine'                          THEN 3
            WHEN ne.rank_max = 12                                        THEN 4
            WHEN ne.rank_max IN (10, 11)                                 THEN
                CASE
                    WHEN o.place = 'city'      THEN 5
                    WHEN ne.pop_max >= 400000  THEN 5
                    ELSE                            6
                END
            WHEN ne.rank_max IN (8, 9)                                   THEN 6
            WHEN ne.rank_max IN (6, 7)                                   THEN 7
            WHEN ne.rank_max = 5                                         THEN 8
            WHEN g.display_max >= 7                                      THEN 9
            WHEN g.display_max >= 5                                      THEN 10
        END,
        CASE o.place
            WHEN 'city'    THEN 10
            WHEN 'town'    THEN 10
            ELSE                12
        END
    )                                                                   AS rank,
    o.geometry
FROM osm.osm_city_point o
LEFT JOIN LATERAL (
    SELECT g.ufi
    FROM aux_data.nga_geonames_populated_places g
    WHERE ST_DWithin(o.geometry, g.geometry, 0.5)
      AND (g.term_dt_f IS NULL OR g.term_dt_f = '')
      AND (lower(o.name) = lower(g.full_nm_nd) OR lower(o.name_en) = lower(g.full_nm_nd))
    ORDER BY ST_Distance(o.geometry, g.geometry)
    LIMIT 1
) g_match ON true
LEFT JOIN LATERAL (
    SELECT
        g.desig_cd,
        split_part(g.display, ',', -1)::int AS display_max
    FROM aux_data.nga_geonames_populated_places g
    WHERE g.ufi = g_match.ufi
      AND g.name_rank::text = '1'
      AND g.nt IN ('C', 'N')
    ORDER BY
        CASE g.nt WHEN 'C' THEN 1 WHEN 'N' THEN 2 ELSE 3 END,
        CASE g.desig_cd
            WHEN 'PPLC'  THEN 1
            WHEN 'PPLCD' THEN 2
            WHEN 'PPL'   THEN 3
            WHEN 'PPLA'  THEN 4
            WHEN 'PPLA2' THEN 5
            WHEN 'PPLA3' THEN 6
            ELSE 7
        END
    LIMIT 1
) g ON true
LEFT JOIN LATERAL (
    SELECT n.rank_max, n.pop_max
    FROM aux_data.ne_10m_populated_places n
    WHERE ST_DWithin(o.geometry, n.geometry, 0.1)
      AND (lower(o.name)    = lower(n.name)
        OR lower(o.name)    = lower(n.nameascii)
        OR lower(o.name_en) = lower(n.name)
        OR lower(o.name_en) = lower(n.nameascii)
        OR lower(n.name)      LIKE lower(o.name) || ',%'
        OR lower(n.nameascii) LIKE lower(o.name) || ',%'
        OR lower(n.name)      LIKE lower(o.name_en) || ',%'
        OR lower(n.nameascii) LIKE lower(o.name_en) || ',%'
        -- Match abbreviated NE names against full OSM names (e.g. "Ft. Worth" vs "Fort Worth")
        OR lower(o.name_en) = replace(lower(n.nameascii), 'ft. ', 'fort ')
        OR lower(o.name)    = replace(lower(n.nameascii), 'ft. ', 'fort ')
        OR lower(o.name_en) = replace(lower(n.nameascii), 'st. ', 'saint ')
        OR lower(o.name)    = replace(lower(n.nameascii), 'st. ', 'saint '))
    ORDER BY
        CASE WHEN lower(o.name)    = lower(n.name)
               OR lower(o.name)    = lower(n.nameascii)
               OR lower(o.name_en) = lower(n.name)
               OR lower(o.name_en) = lower(n.nameascii)   THEN 0
             ELSE 1
        END,
        n.rank_max DESC,
        ST_Distance(o.geometry, n.geometry)
    LIMIT 1
) ne ON true
WHERE o.place IN ('city', 'town')
  AND o.osm_id != 12350920517  -- Greater Tunb: island polygon (160056026) takes precedence

UNION ALL

-- Villages and hamlets: OSM fallback only.
SELECT
    o.osm_id,
    NULLIF(o.name, '')                                                  AS name,
    NULLIF(o.name_en, '')                                               AS name_en,
    o.place                                                             AS class,
    CASE o.place
        WHEN 'village'       THEN 3
        WHEN 'suburb'        THEN 4
        WHEN 'neighbourhood' THEN 5
        WHEN 'hamlet'        THEN 6
        ELSE                      7
    END                                                                 AS class_rank,
    CASE
        WHEN o.name_en = 'Taipei'               THEN NULL  -- DOS Bulletin 37: Taipei must not be symbolized as capital of a sovereign state
        WHEN o.capital = 'yes'                  THEN 2
        WHEN o.capital IN ('2','3','5','6')     THEN o.capital::int
        WHEN o.capital = '4'                    THEN 3
    END                                                                 AS capital,
    CASE o.place
        WHEN 'village'       THEN 11
        WHEN 'hamlet'        THEN 11
        WHEN 'suburb'        THEN 11
        WHEN 'neighbourhood' THEN 11
        ELSE                      12
    END                                                                 AS rank,
    o.geometry
FROM osm.osm_city_point o
WHERE o.place IN ('village', 'hamlet', 'suburb', 'neighbourhood')

UNION ALL

-- Islands from polygons: rank derived from area using OMT thresholds (m²).
-- Label placed at polygon centroid.
SELECT
    osm_id,
    NULLIF(name, '')                                                    AS name,
    CASE osm_id
        WHEN  468798441 THEN 'Abu Musa'    -- NGA Guide: drop "Island" suffix
        WHEN   -2103185 THEN 'Etorofu'     -- NGA Guide: Japanese name for Iturup
        WHEN   -2409701 THEN 'Kunashiri'   -- NGA Guide: Japanese name for Kunashir
        WHEN   -9687998 THEN 'Habomai'     -- NGA Guide: Japanese name for Ostrov Zelenyy
        ELSE NULLIF(name_en, '')
    END                                                                 AS name_en,
    'island'::text                                                      AS class,
    NULL::int                                                           AS class_rank,
    NULL::int                                                           AS capital,
    CASE
        WHEN ST_Area(geometry::geography) >= 1e12 THEN 1
        WHEN ST_Area(geometry::geography) >= 1e11 THEN 2
        WHEN ST_Area(geometry::geography) >= 8e9  THEN 3
        WHEN ST_Area(geometry::geography) >= 1e9  THEN 4
        WHEN ST_Area(geometry::geography) >= 1e8  THEN 5
        WHEN ST_Area(geometry::geography) >= 1e7  THEN 6
        ELSE                                           7
    END                                                                 AS rank,
    ST_PointOnSurface(
        ST_MakeValid(geometry)
    )::geometry(Point, 4326)                                            AS geometry
FROM osm.osm_island_polygon
WHERE NULLIF(name, '') IS NOT NULL

UNION ALL

-- Islands from points: only where no polygon with the same name exists nearby.
-- Avoids duplicating labels for islands mapped as both polygon and node.
SELECT
    osm_id,
    NULLIF(name, '')                                                    AS name,
    NULLIF(name_en, '')                                                 AS name_en,
    'island'::text                                                      AS class,
    NULL::int                                                           AS class_rank,
    NULL::int                                                           AS capital,
    7                                                                   AS rank,
    geometry
FROM osm.osm_island_point p
WHERE NULLIF(name, '') IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM osm.osm_island_polygon poly
      WHERE NULLIF(poly.name, '') IS NOT NULL
        AND (lower(poly.name) = lower(p.name) OR lower(poly.name_en) = lower(p.name_en))
        AND ST_DWithin(poly.geometry, p.geometry, 0.1)
  )

UNION ALL

-- Island groups from NE geography regions (Spratly Islands, Aleutians, etc.)
SELECT
    NULL::bigint                                                        AS osm_id,
    NULLIF(name, '')                                                    AS name,
    NULLIF(name_en, '')                                                 AS name_en,
    'island_group'::text                                                AS class,
    NULL::int                                                           AS class_rank,
    NULL::int                                                           AS capital,
    scalerank + 1                                                       AS rank,
    ST_PointOnSurface(
        ST_MakeValid(geometry)
    )::geometry(Point, 4326)                                            AS geometry
FROM aux_data.ne_10m_geography_regions_polys
WHERE featurecla = 'Island group'
  AND NULLIF(name, '') IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_populated_places_geometry
    ON export.place_labels USING gist(geometry);
CREATE INDEX IF NOT EXISTS idx_populated_places_rank
    ON export.place_labels USING btree(rank);
CREATE INDEX IF NOT EXISTS idx_populated_places_capital
    ON export.place_labels USING btree(capital) WHERE capital IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_populated_places_class
    ON export.place_labels USING btree(class);
CREATE INDEX IF NOT EXISTS idx_populated_places_name
    ON export.place_labels USING btree(name) WHERE name IS NOT NULL;
COMMIT;