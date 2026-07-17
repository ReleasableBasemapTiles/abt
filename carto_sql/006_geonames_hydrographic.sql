-- =============================================================================
-- LAYER: Hydrographic Labels
-- Schema:  export
-- Sources: aux_data.nga_geonames_hydrographic       (global coverage minus US)
--          aux_data.usgs_domestic_names             (US coverage)
--          aux_data.ne_10m_geography_marine_polys   (curated major water bodies)
-- =============================================================================


-- -----------------------------------------------------------------------------
-- export.hydrographic_label — combined hydrographic label points
--   (GeoNames + USGS Domestic Names + Natural Earth marine polygons)
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.hydrographic_label CASCADE;
CREATE MATERIALIZED VIEW export.hydrographic_label AS
WITH geonames_hydro AS (
    -- NGA GeoNames hydrographic — global coverage except the US (NGA defers
    -- to USGS/BGN for domestic US names; supplemented below by usgs_hydro).
    SELECT DISTINCT ON (h.geometry)
        h.full_nm_nd            AS name,
        h.desig_cd,
        h.name_rank,
        h.display,
        NULL::integer           AS scalerank,
        NULL::double precision  AS min_label,
        h.geometry
    FROM aux_data.nga_geonames_hydrographic h
    WHERE h.nt IN ('N', 'C', 'D')
    ORDER BY h.geometry,
        CASE
            WHEN h.nt = 'C' AND h.full_nm_nd IS NOT NULL THEN 1
            WHEN h.nt = 'N' AND h.full_nm_nd IS NOT NULL THEN 2
            WHEN h.nt = 'D' AND h.full_nm_nd IS NOT NULL THEN 3
            WHEN h.nt = 'C' AND h.full_nm_nd IS NULL     THEN 4
            WHEN h.nt = 'N' AND h.full_nm_nd IS NULL     THEN 5
            WHEN h.nt = 'D' AND h.full_nm_nd IS NULL     THEN 6
            ELSE 7
        END
),
usgs_hydro AS (
    -- USGS Domestic Names — fills the US coverage gap left by GeoNames.
    -- feature_class is mapped to the closest GeoNames desig_cd equivalent so
    -- it flows through the same `class` CASE below (arroyo = wadi, gut = narrows).
    SELECT
        u.feature_name AS name,
        CASE u.feature_class
            WHEN 'Stream'    THEN 'STM'
            WHEN 'Reservoir' THEN 'RSV'
            WHEN 'Lake'      THEN 'LK'
            WHEN 'Spring'    THEN 'SPNG'
            WHEN 'Canal'     THEN 'CNL'
            WHEN 'Bay'       THEN 'BAY'
            WHEN 'Swamp'     THEN 'SWMP'
            WHEN 'Basin'     THEN 'BSND'
            WHEN 'Channel'   THEN 'CHN'
            WHEN 'Gut'       THEN 'NRWS'
            WHEN 'Bend'      THEN 'STMB'
            WHEN 'Falls'     THEN 'FLLS'
            WHEN 'Rapids'    THEN 'RPDS'
            WHEN 'Glacier'   THEN 'GLCR'
            WHEN 'Arroyo'    THEN 'WAD'
            WHEN 'Sea'       THEN 'SEA'
        END                       AS desig_cd,
        NULL::character varying   AS name_rank,
        NULL::character varying   AS display,
        NULL::integer             AS scalerank,
        NULL::double precision    AS min_label,
        u.geometry
    FROM aux_data.usgs_domestic_names u
    WHERE u.feature_class IN (
        'Stream','Reservoir','Lake','Spring','Canal','Bay','Swamp','Basin',
        'Channel','Gut','Bend','Falls','Rapids','Glacier','Arroyo','Sea'
    )
    AND u.bgn_type = 'Official'
    AND NULLIF(u.feature_name, '') IS NOT NULL
),
ne_water AS (
    -- Natural Earth marine polygons — curated major water bodies (oceans, seas, gulfs, bays, major lakes). 
    SELECT
        -- NE has not yet picked up the US renaming of "Gulf of Mexico" to "Gulf of America" (USGS Domestic Names already reflects it). Normalize here at the source.
        CASE
            WHEN NULLIF(n.name, '') ILIKE 'Gulf of Mexico' THEN 'Gulf of America'
            ELSE NULLIF(n.name, '')
        END                       AS name,
        CASE lower(n.featurecla)
            WHEN 'ocean' THEN 'OCN'
            WHEN 'sea'   THEN 'SEA'
            WHEN 'bay'   THEN 'BAY'
            WHEN 'gulf'  THEN 'GULF'
            WHEN 'lake'  THEN 'LK'
            ELSE NULL
        END                       AS desig_cd,
        NULL::character varying   AS name_rank,
        NULL::character varying   AS display,
        n.scalerank,
        n.min_label,
        ST_PointOnSurface(n.geometry) AS geometry
    FROM aux_data.ne_10m_geography_marine_polys n
    WHERE NULLIF(n.name, '') IS NOT NULL
      AND lower(n.featurecla) IN ('ocean','sea','bay','gulf','lake')
),
ne_lakes AS (
    -- Natural Earth major lakes
    SELECT
        NULLIF(l.name, '')        AS name,
        CASE lower(l.featurecla)
            WHEN 'lake'             THEN 'LK'
            WHEN 'intermittent lake' THEN 'LKI'
            WHEN 'reservoir'        THEN 'RSV'
            ELSE 'LK'
        END                       AS desig_cd,
        NULL::character varying   AS name_rank,
        NULL::character varying   AS display,
        l.scalerank::integer      AS scalerank,
        l.min_label,
        ST_PointOnSurface(l.geometry) AS geometry
    FROM aux_data.ne_10m_lakes l
    WHERE NULLIF(l.name, '') IS NOT NULL
      AND lower(l.featurecla) IN ('lake','intermittent lake','reservoir','alkaline lake')
      AND l.scalerank IS NOT NULL
),
combined AS (
    -- NE-curated rows always win for major water bodies
    SELECT * FROM ne_water
    UNION ALL
    SELECT * FROM ne_lakes
    UNION ALL
    SELECT g.* FROM geonames_hydro g
    WHERE NOT EXISTS (
        SELECT 1 FROM ne_water n  WHERE lower(n.name) = lower(g.name)
    )
    AND NOT EXISTS (
        SELECT 1 FROM ne_lakes l WHERE lower(l.name) = lower(g.name)
    )
    UNION ALL
    SELECT u.* FROM usgs_hydro u
    WHERE NOT EXISTS (
        SELECT 1 FROM ne_water n  WHERE lower(n.name) = lower(u.name)
    )
    AND NOT EXISTS (
        SELECT 1 FROM ne_lakes l WHERE lower(l.name) = lower(u.name)
    )
)
SELECT
    c.name,
    c.desig_cd,
    CASE
        WHEN c.desig_cd = 'BAY'    THEN 'bay(s)'
        WHEN c.desig_cd = 'BGHT'   THEN 'bight(s)'
        WHEN c.desig_cd = 'BNK'    THEN 'bank(s)'
        WHEN c.desig_cd = 'BNKR'   THEN 'stream bank'
        WHEN c.desig_cd = 'BNKX'   THEN 'section of bank'
        WHEN c.desig_cd = 'BOG'    THEN 'bog(s)'
        WHEN c.desig_cd = 'BSND'   THEN 'basin'
        WHEN c.desig_cd = 'BSNP'   THEN 'basin'
        WHEN c.desig_cd = 'BSNU'   THEN 'basin'
        WHEN c.desig_cd = 'CAPG'   THEN 'icecap'
        WHEN c.desig_cd = 'CHN'    THEN 'channel'
        WHEN c.desig_cd = 'CHNL'   THEN 'lake channel(s)'
        WHEN c.desig_cd = 'CHNM'   THEN 'marine channel'
        WHEN c.desig_cd = 'CNFL'   THEN 'confluence'
        WHEN c.desig_cd = 'CNL'    THEN 'canal'
        WHEN c.desig_cd = 'CNLA'   THEN 'aqueduct'
        WHEN c.desig_cd = 'COVE'   THEN 'cove(s)'
        WHEN c.desig_cd = 'CRKT'   THEN 'tidal creek(s)'
        WHEN c.desig_cd = 'DOMG'   THEN 'icecap dome'
        WHEN c.desig_cd = 'DPRG'   THEN 'icecap depression'
        WHEN c.desig_cd = 'ESTY'   THEN 'estuary'
        WHEN c.desig_cd = 'FISH'   THEN 'fishing area'
        WHEN c.desig_cd = 'FJD'    THEN 'fjord(s)'
        WHEN c.desig_cd = 'FLLS'   THEN 'waterfall(s)'
        WHEN c.desig_cd = 'FLLSX'  THEN 'section of waterfall(s)'
        WHEN c.desig_cd = 'FLTM'   THEN 'mud flat(s)'
        WHEN c.desig_cd = 'FLTT'   THEN 'tidal flat(s)'
        WHEN c.desig_cd = 'GLCR'   THEN 'glacier(s)'
        WHEN c.desig_cd = 'GULF'   THEN 'gulf'
        WHEN c.desig_cd = 'GYSR'   THEN 'geyser'
        WHEN c.desig_cd = 'HBR'    THEN 'harbor(s)'
        WHEN c.desig_cd = 'HBRX'   THEN 'section of harbor'
        WHEN c.desig_cd = 'INLT'   THEN 'inlet'
        WHEN c.desig_cd = 'LBED'   THEN 'lake bed(s)'
        WHEN c.desig_cd = 'LGN'    THEN 'lagoon(s)'
        WHEN c.desig_cd = 'LGNX'   THEN 'section of lagoon'
        WHEN c.desig_cd = 'LK'     THEN 'lake'
        WHEN c.desig_cd = 'LKC'    THEN 'crater lake(s)'
        WHEN c.desig_cd = 'LKI'    THEN 'intermittent lake(s)'
        WHEN c.desig_cd = 'LKN'    THEN 'salt lake(s)'
        WHEN c.desig_cd = 'LKNI'   THEN 'intermittent salt lake(s)'
        WHEN c.desig_cd = 'LKO'    THEN 'oxbow lake'
        WHEN c.desig_cd = 'LKOI'   THEN 'intermittent oxbow lake'
        WHEN c.desig_cd = 'LKS'    THEN 'lakes'
        WHEN c.desig_cd = 'LKSB'   THEN 'underground lake'
        WHEN c.desig_cd = 'LKX'    THEN 'section of lake'
        WHEN c.desig_cd = 'MFGN'   THEN 'salt evaporation ponds'
        WHEN c.desig_cd = 'MGV'    THEN 'mangrove swamp'
        WHEN c.desig_cd = 'MOOR'   THEN 'moor(s)'
        WHEN c.desig_cd = 'MRSH'   THEN 'marsh(es)'
        WHEN c.desig_cd = 'MRSHN'  THEN 'salt marsh'
        WHEN c.desig_cd = 'NRWS'   THEN 'narrows'
        WHEN c.desig_cd = 'OCN'    THEN 'ocean'
        WHEN c.desig_cd = 'OVF'    THEN 'overfalls'
        WHEN c.desig_cd = 'PND'    THEN 'pond(s)'
        WHEN c.desig_cd = 'PNDI'   THEN 'intermittent pond(s)'
        WHEN c.desig_cd = 'PNDN'   THEN 'salt pond(s)'
        WHEN c.desig_cd = 'PNDNI'  THEN 'intermittent salt pond(s)'
        WHEN c.desig_cd = 'PNDSF'  THEN 'fishponds'
        WHEN c.desig_cd = 'POOL'   THEN 'pool(s)'
        WHEN c.desig_cd = 'POOLI'  THEN 'intermittent pool'
        WHEN c.desig_cd = 'RCH'    THEN 'reach'
        WHEN c.desig_cd = 'RDGG'   THEN 'icecap ridge'
        WHEN c.desig_cd = 'RDST'   THEN 'roadstead'
        WHEN c.desig_cd = 'RF'     THEN 'reef(s)'
        WHEN c.desig_cd = 'RFC'    THEN 'coral reef(s)'
        WHEN c.desig_cd = 'RFX'    THEN 'section of reef'
        WHEN c.desig_cd = 'RPDS'   THEN 'rapids'
        WHEN c.desig_cd = 'RSV'    THEN 'reservoir(s)'
        WHEN c.desig_cd = 'RSVI'   THEN 'intermittent reservoir'
        WHEN c.desig_cd = 'RSVT'   THEN 'water tank'
        WHEN c.desig_cd = 'RVN'    THEN 'ravine(s)'
        WHEN c.desig_cd = 'SBKH'   THEN 'sabkha(s)'
        WHEN c.desig_cd = 'SD'     THEN 'sound'
        WHEN c.desig_cd = 'SEA'    THEN 'sea'
        WHEN c.desig_cd = 'SHOL'   THEN 'shoal(s)'
        WHEN c.desig_cd = 'SPNG'   THEN 'spring(s)'
        WHEN c.desig_cd = 'SPNS'   THEN 'sulphur spring(s)'
        WHEN c.desig_cd = 'SPNT'   THEN 'hot spring(s)'
        WHEN c.desig_cd = 'STM'    THEN 'stream(s)'
        WHEN c.desig_cd = 'STMA'   THEN 'anabranch'
        WHEN c.desig_cd = 'STMB'   THEN 'stream bend'
        WHEN c.desig_cd = 'STMC'   THEN 'canalized stream'
        WHEN c.desig_cd = 'STMD'   THEN 'distributary(-ies)'
        WHEN c.desig_cd = 'STMH'   THEN 'headwaters'
        WHEN c.desig_cd = 'STMI'   THEN 'intermittent stream'
        WHEN c.desig_cd = 'STMIX'  THEN 'section of intermittent stream'
        WHEN c.desig_cd = 'STMM'   THEN 'stream mouth(s)'
        WHEN c.desig_cd = 'STMQ'   THEN 'abandoned watercourse'
        WHEN c.desig_cd = 'STMSB'  THEN 'lost river'
        WHEN c.desig_cd = 'STMX'   THEN 'section of stream'
        WHEN c.desig_cd = 'STRT'   THEN 'strait'
        WHEN c.desig_cd = 'SWMP'   THEN 'swamp'
        WHEN c.desig_cd = 'SYSI'   THEN 'irrigation system'
        WHEN c.desig_cd = 'TNLC'   THEN 'canal tunnel'
        WHEN c.desig_cd = 'WAD'    THEN 'wadi(s)'
        WHEN c.desig_cd = 'WADB'   THEN 'wadi bend'
        WHEN c.desig_cd = 'WADJ'   THEN 'wadi junction'
        WHEN c.desig_cd = 'WADM'   THEN 'wadi mouth'
        WHEN c.desig_cd = 'WADX'   THEN 'section of wadi'
        WHEN c.desig_cd = 'WHRL'   THEN 'whirlpool'
        WHEN c.desig_cd = 'WLL'    THEN 'water well(s)'
        WHEN c.desig_cd = 'WLLQ'   THEN 'abandoned well'
        WHEN c.desig_cd = 'WTLD'   THEN 'wetland'
        WHEN c.desig_cd = 'WTLDI'  THEN 'intermittent wetland'
        WHEN c.desig_cd = 'WTRH'   THEN 'waterhole(s)'
        ELSE NULL
    END                                                             AS class,
    c.name_rank,
    c.display,
    c.scalerank,
    c.min_label,
    c.geometry
FROM combined c;

CREATE INDEX idx_geonames_hydrographic_geometry  ON export.hydrographic_label USING gist(geometry);
CREATE INDEX idx_geonames_hydrographic_class     ON export.hydrographic_label USING btree(class);
CREATE INDEX idx_geonames_hydrographic_scalerank ON export.hydrographic_label USING btree(scalerank);
CREATE INDEX idx_geonames_hydrographic_name      ON export.hydrographic_label USING btree(name) WHERE name IS NOT NULL;
COMMIT;
